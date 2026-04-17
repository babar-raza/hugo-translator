#!/usr/bin/env python3
"""Auto-discover technical terms from source content and add to protection config.

Scans English source files, discovers technical terms (file format acronyms,
API identifiers, product names, …) using pattern-based analysis, deduplicates
against already-protected terms, then:

  - Auto-applies high-confidence terms (≥ --high-confidence) to
    config/terminology.yaml  global.exact_matches
  - Saves medium-confidence terms (≥ --mid-confidence) to
    config/terminology/pending_review.yaml for human review

After running, restart workers or reload config for changes to take effect.

Usage:
    python scripts/discover_and_protect_terms.py [options]

Examples:
    # Dry-run to preview discoveries without modifying any file
    python scripts/discover_and_protect_terms.py --dry-run

    # Scan only the blog site with a higher frequency threshold
    python scripts/discover_and_protect_terms.py --site blog.aspose.net --min-frequency 10

    # Override the content root
    python scripts/discover_and_protect_terms.py --content-root D:/repos/aspose.net/content
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Set

# Make sure project root is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from src.translation_engine.terminology.discovery import DiscoveredTerm, TerminologyDiscovery

# ── Default thresholds ────────────────────────────────────────────────────────
DEFAULT_HIGH_CONFIDENCE = 0.85   # auto-apply to terminology.yaml
DEFAULT_MID_CONFIDENCE  = 0.65   # save to pending_review.yaml for human review
DEFAULT_MIN_FREQUENCY   = 8      # minimum occurrences across the corpus
DEFAULT_MAX_FILES       = 5_000  # cap corpus size to avoid memory issues
# ─────────────────────────────────────────────────────────────────────────────


def load_global_config() -> dict:
    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def collect_english_files(content_roots: List[Path], max_files: int) -> List[Path]:
    """Return paths of English source .md files from all content roots.

    Skips translated files by two heuristics:
    1. Stem pattern: ``index.ar.md`` — has a 2-char language code in the stem.
    2. Folder pattern: file lives inside a non-English language folder (``/ar/``, ``/bg/``).
    """
    files: List[Path] = []
    lang_code_re = re.compile(r'^[a-z]{2}(-[A-Z]{2})?$')

    for root in content_roots:
        if not root.is_dir():
            continue
        for md in sorted(root.rglob("*.md")):
            if len(files) >= max_files:
                break
            # Skip translated-filename pattern: index.ar.md
            stem_parts = md.name.split(".")
            if len(stem_parts) >= 3:
                lang_part = stem_parts[-2]
                if len(lang_part) == 2 and lang_part.islower() and lang_part != 'en':
                    continue
            # Skip files inside non-English language subfolders
            in_non_english_folder = any(
                lang_code_re.match(part) and part != 'en'
                for part in md.parts
            )
            if in_non_english_folder:
                continue
            files.append(md)
        if len(files) >= max_files:
            break

    return files[:max_files]


def read_corpus(files: List[Path]) -> List[str]:
    corpus: List[str] = []
    for p in files:
        try:
            corpus.append(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return corpus


def load_existing_terms(terminology_yaml: Path) -> Set[str]:
    """Collect all currently-known term texts (lower-cased) to avoid duplicates.

    Reads from:
    - config/terminology.yaml          (primary — global + site_overrides)
    - config/terminology/protected_terms.yaml
    - config/terminology/aspose_terms.txt
    - config/terminology/technical_terms.yaml
    """
    known: Set[str] = set()

    def _harvest_yaml_rules(data: dict) -> None:
        def _from_section(section: dict) -> None:
            for rule in section.get("exact_matches", []):
                if term := rule.get("term"):
                    known.add(str(term).lower())
        _from_section(data.get("global", {}))
        for site_data in data.get("site_overrides", {}).values():
            _from_section(site_data)

    for yaml_path in [terminology_yaml, Path("config/terminology/protected_terms.yaml")]:
        if yaml_path.exists():
            with open(yaml_path, encoding="utf-8") as f:
                _harvest_yaml_rules(yaml.safe_load(f) or {})

    flat_txt = Path("config/terminology/aspose_terms.txt")
    if flat_txt.exists():
        for line in flat_txt.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                known.add(line.lower())

    tech_yaml = Path("config/terminology/technical_terms.yaml")
    if tech_yaml.exists():
        data = yaml.safe_load(tech_yaml.read_text(encoding="utf-8")) or {}
        for term in data.get("terms", []):
            known.add(str(term).lower())

    return known


def apply_to_terminology_yaml(
    terms: List[DiscoveredTerm],
    terminology_yaml: Path,
    dry_run: bool,
) -> List[DiscoveredTerm]:
    """Append terms to global.exact_matches in terminology.yaml.

    Returns the list of terms actually added (deduped against file contents).
    """
    with open(terminology_yaml, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    existing_in_file: Set[str] = {
        r["term"].lower()
        for r in data.get("global", {}).get("exact_matches", [])
        if "term" in r
    }

    added: List[DiscoveredTerm] = []
    exact_matches = data.setdefault("global", {}).setdefault("exact_matches", [])

    for term in terms:
        if term.term_text.lower() in existing_in_file:
            continue
        exact_matches.append({
            "term": term.term_text,
            "category": term.category,
            "case_sensitive": True,
            "preserve_mode": "protect",
            "severity": "info",
            "description": (
                f"auto-discovered: freq={term.frequency}, "
                f"conf={term.confidence:.2f}"
            ),
        })
        existing_in_file.add(term.term_text.lower())
        added.append(term)

    if added and not dry_run:
        with open(terminology_yaml, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)

    return added


def save_pending_review(
    terms: List[DiscoveredTerm],
    output_path: Path,
    dry_run: bool,
) -> int:
    """Merge medium-confidence terms into pending_review.yaml.

    Returns the count of newly added entries.
    """
    existing_data: dict = {}
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            existing_data = yaml.safe_load(f) or {}

    already_pending: Set[str] = {
        entry["term"].lower()
        for entry in existing_data.get("pending_terms", [])
        if "term" in entry
    }

    new_entries = []
    for term in terms:
        if term.term_text.lower() in already_pending:
            continue
        new_entries.append({
            "term": term.term_text,
            "category": term.category,
            "frequency": term.frequency,
            "confidence": round(term.confidence, 2),
            "examples": term.examples[:2],
            "status": "pending_review",
            "suggested_rule": {
                "preserve_mode": "protect",
                "severity": "info",
                "case_sensitive": True,
            },
        })

    if new_entries and not dry_run:
        existing_data.setdefault("pending_terms", []).extend(new_entries)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)

    return len(new_entries)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--content-root",
        help="Path to content root (default: content_root from config/global.yaml)",
    )
    parser.add_argument(
        "--site",
        help="Scan only this site subfolder (e.g. blog.aspose.net)",
    )
    parser.add_argument(
        "--high-confidence",
        type=float,
        default=DEFAULT_HIGH_CONFIDENCE,
        metavar="FLOAT",
        help=f"Auto-apply threshold (default: {DEFAULT_HIGH_CONFIDENCE})",
    )
    parser.add_argument(
        "--mid-confidence",
        type=float,
        default=DEFAULT_MID_CONFIDENCE,
        metavar="FLOAT",
        help=f"Pending-review threshold (default: {DEFAULT_MID_CONFIDENCE})",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=DEFAULT_MIN_FREQUENCY,
        metavar="N",
        help=f"Minimum occurrences in corpus (default: {DEFAULT_MIN_FREQUENCY})",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        metavar="N",
        help=f"Max source files to scan (default: {DEFAULT_MAX_FILES})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discoveries without modifying any file",
    )
    args = parser.parse_args()

    # ── 1. Resolve content root(s) ───────────────────────────────────────────
    global_cfg = load_global_config()
    content_root_str = (
        args.content_root
        or global_cfg.get("translation", {}).get("content_root")
        or global_cfg.get("content_root", "")
        or "./content"
    )

    base = Path(content_root_str).expanduser()
    if args.site:
        content_roots = [base / args.site]
    elif base.is_dir():
        # All site subfolders
        content_roots = [d for d in sorted(base.iterdir()) if d.is_dir()]
    else:
        print(f"ERROR: content root not found: {base}")
        sys.exit(1)

    # ── 2. Collect corpus ────────────────────────────────────────────────────
    print(f"Scanning English source files across {len(content_roots)} site(s) "
          f"(max {args.max_files} files)…")
    files = collect_english_files(content_roots, args.max_files)
    print(f"  Found {len(files)} English source files")

    if not files:
        print("No English source files found. Check --content-root.")
        sys.exit(1)

    print("  Reading corpus…", end=" ", flush=True)
    corpus = read_corpus(files)
    total_chars = sum(len(t) for t in corpus)
    print(f"{total_chars:,} chars")

    # ── 3. Run discovery ─────────────────────────────────────────────────────
    disc_config = {
        "enabled": True,           # bypass the enabled=False guard in TerminologyDiscovery
        "min_frequency": args.min_frequency,
        "confidence_threshold": args.mid_confidence,  # lower bar; we split later
    }
    discovery = TerminologyDiscovery(disc_config)
    print(f"\nRunning term discovery "
          f"(min_frequency={args.min_frequency}, "
          f"mid_threshold={args.mid_confidence}, "
          f"high_threshold={args.high_confidence})…")
    all_discovered = discovery.discover_terms(corpus)
    print(f"  Discovered {len(all_discovered)} candidate terms above mid-confidence threshold")

    # ── 4. Deduplicate against already-protected terms ───────────────────────
    terminology_yaml = Path("config/terminology.yaml")
    existing = load_existing_terms(terminology_yaml)
    fresh = [t for t in all_discovered if t.term_text.lower() not in existing]
    skipped = len(all_discovered) - len(fresh)
    print(f"  {skipped} already protected  |  {len(fresh)} new")

    if not fresh:
        print("\nNothing new to add — all discovered terms are already protected.")
        return

    # ── 5. Split by confidence tier ──────────────────────────────────────────
    high_conf = [t for t in fresh if t.confidence >= args.high_confidence]
    mid_conf  = [t for t in fresh
                 if args.mid_confidence <= t.confidence < args.high_confidence]

    # ── 6. Auto-apply high-confidence terms ──────────────────────────────────
    prefix = "[DRY-RUN] " if args.dry_run else ""
    if high_conf:
        added = apply_to_terminology_yaml(high_conf, terminology_yaml, args.dry_run)
        print(f"\n{prefix}Auto-applied {len(added)} high-confidence terms "
              f"→ config/terminology.yaml:")
        for t in sorted(added, key=lambda x: (-x.confidence, x.term_text)):
            print(f"  + {t.term_text:<30}  [{t.category:<18}]  "
                  f"freq={t.frequency:>4}  conf={t.confidence:.2f}")
    else:
        print("\nNo new high-confidence terms to auto-apply.")

    # ── 7. Save medium-confidence terms for review ───────────────────────────
    pending_path = Path("config/terminology/pending_review.yaml")
    if mid_conf:
        n_new = save_pending_review(mid_conf, pending_path, args.dry_run)
        print(f"\n{prefix}Saved {n_new} medium-confidence terms "
              f"→ {pending_path}:")
        for t in sorted(mid_conf, key=lambda x: (-x.confidence, x.term_text))[:25]:
            print(f"  ? {t.term_text:<30}  [{t.category:<18}]  "
                  f"freq={t.frequency:>4}  conf={t.confidence:.2f}")
        if len(mid_conf) > 25:
            print(f"  … and {len(mid_conf) - 25} more (see {pending_path})")
    else:
        print("\nNo medium-confidence terms for review.")

    # ── 8. Summary ───────────────────────────────────────────────────────────
    print()
    if args.dry_run:
        print("Dry-run complete — no files were modified.")
    else:
        if high_conf:
            print(f"Done. {len(high_conf)} new terms protected in config/terminology.yaml.")
            print("Restart workers (or they will pick it up on next run) for changes to take effect.")
        if mid_conf:
            print(f"Review {pending_path} and promote terms you approve.")


if __name__ == "__main__":
    main()
