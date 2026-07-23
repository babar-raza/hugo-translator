"""
tm_surgical_cleanup.py — Scan L2 TM for corrupt entries and selectively fix them.

Corruption categories (reference.aspose.org):
  1. PascalCase class/interface names were sent to model → translated incorrectly.
     Action: overwrite with identity mapping (source_text == translation).
  2. Known artifact patterns leaked into translation (IHeadingPair, مُحملة مكان, shortcodes).
     Action: delete entry so next translation produces a clean result.
  3. API heading terms translated with garbage content (_contains_corruption detector).
     Action: delete entry.

Usage:
  python scripts/quality/tm_surgical_cleanup.py --dry-run       # default
  python scripts/quality/tm_surgical_cleanup.py --apply
  python scripts/quality/tm_surgical_cleanup.py --apply --site reference.aspose.org
  python scripts/quality/tm_surgical_cleanup.py --apply --locales ar,bg,ru
  python scripts/quality/tm_surgical_cleanup.py --apply --max-changes 5000
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.translation_engine.terminology.classification import (  # noqa: E402
    TemplateStringRegistry,
)
from tm.l2_persistent import L2PersistentTM, TranslationEntry  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SITE = "reference.aspose.org"
DEFAULT_TM_PATH = Path("data/tm/l2.lmdb")

_API_HEADING_TERMS: frozenset[str] = frozenset(
    {
        "Name",
        "Type",
        "Description",
        "Returns",
        "Parameters",
        "Properties",
        "Methods",
        "Fields",
        "Constructors",
        "Events",
        "Exceptions",
        "Remarks",
        "Examples",
        "See Also",
        "Inheritance",
        "Implements",
        "Namespace",
        "Assembly",
        "Syntax",
        "Value",
    }
)

# Matches any PascalCase / dotted identifier that should never be translated
_IDENTIFIER_RE = re.compile(r"^[A-Z][a-zA-Z0-9_.]+$")

# Known artifact fragments produced by NLLB / m2m100 / template corruption
_ARTIFACT_FRAGMENTS = [
    "(مُحملة مكان)",  # NLLB Arabic placeholder artifact
    "IHeadingPair",  # COM interface name leaked into translation
    "{{<",  # Hugo shortcode leak
    "{{%",  # Hugo shortcode leak
    "{\\pos",  # SSA subtitle position tag
]


# ---------------------------------------------------------------------------
# Corruption detectors
# ---------------------------------------------------------------------------


def _contains_corruption(text: str, source_text: str | None = None) -> bool:
    """Universal corruption detector (same logic as write_gate._contains_corruption)."""
    if "{{<" in text or "{{%" in text:
        return True
    # Artifact wrapper: { followed immediately by non-ASCII character
    if re.search(r"\{[^\x00-\x7F]", text):
        return True
    # Hallucination padding: >3x source length
    if source_text and len(text) > 3 * len(source_text):
        return True
    return False


def _has_artifact(translation: str) -> bool:
    """Return True if translation contains any known artifact fragment."""
    return any(frag in translation for frag in _ARTIFACT_FRAGMENTS)


def is_corrupt_entry(
    entry: TranslationEntry, registry: TemplateStringRegistry | None = None
) -> tuple[bool, str, str]:
    """
    Determine if a TM entry is corrupt.

    Returns:
        (is_corrupt, reason, action)
        action is 'overwrite' (identity), 'delete', or 'correct' (replace with
        the approved i18n template-string table value — see Rule 4).
    """
    src = entry.source_text.strip()
    tgt = entry.translation.strip()

    # Guard (found via TC-HT-I18N-008's own test suite, not pre-existing
    # knowledge): Rule 1 below matches ANY single capitalized word of 4+
    # letters, including "Overview"/"Properties"/etc — the exact over-broad
    # shape this whole mission exists to stop trusting (see
    # classification.py's module docstring). Without this guard, Rule 1
    # would flag a CORRECT, agentically-reviewed translation like
    # "Overview" -> "概要" as "identifier_translated" and tell --apply to
    # revert it to an English identity mapping, destroying a good
    # translation. If the table says this is exactly the approved value,
    # it is never corrupt, full stop — checked before any other rule.
    if registry is not None:
        approved_value = registry.lookup(src, entry.tgt_lang)
        if approved_value is not None and tgt == approved_value:
            return False, "", ""

    # Rule 1: PascalCase / dotted identifier should never be translated.
    # Require len >= 4 to avoid false-positives on short common words.
    if len(src) >= 4 and _IDENTIFIER_RE.match(src) and tgt != src:
        return True, "identifier_translated", "overwrite"

    # Rule 2: Known artifact fragments in translation
    if _has_artifact(tgt):
        return True, "artifact_in_translation", "delete"

    # Rule 3: API heading term translated with corrupt/garbage content
    if src in _API_HEADING_TERMS and _contains_corruption(tgt, src):
        return True, "heading_term_corrupted", "delete"

    # Rule 4 (mission heading-i18n-governance-20260723, TC-HT-I18N-008): a
    # known template-string term whose TM entry is an untranslated English
    # passthrough (src == tgt) — the root-cause bug this mission fixes
    # (text_unit_extractor.py's over-broad single-hump PascalCase heuristic,
    # see classification.py's module docstring) poisoned exactly this shape
    # of entry historically. Since TC-HT-I18N-004 now resolves table hits
    # BEFORE any TM read/write, this rule only matters for entries cached
    # before that fix landed — but those entries would otherwise keep
    # resurfacing for any code path that still consults TM directly.
    if registry is not None and src == tgt:
        approved_value = registry.lookup(src, entry.tgt_lang)
        if approved_value is not None and approved_value != src:
            return True, "heading_untranslated_passthrough", "correct"

    return False, "", ""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(
    tm: L2PersistentTM,
    site: str | None,
    only_locales: list[str] | None,
    apply: bool,
    max_changes: int,
    verbose: bool,
    registry: TemplateStringRegistry | None = None,
) -> dict:
    stats: dict = defaultdict(int)

    # Collect corrupt entries first (cannot mutate LMDB while iterating cursor)
    to_overwrite: list[TranslationEntry] = []
    to_delete: list[TranslationEntry] = []
    to_correct: list[tuple[TranslationEntry, str]] = []

    print(f"Scanning L2 TM (site={site or 'ALL'}, locales={only_locales or 'ALL'})...")

    for entry in tm.export_iter(site_id=site):
        stats["scanned"] += 1

        if only_locales and entry.tgt_lang not in only_locales:
            continue

        corrupt, reason, action = is_corrupt_entry(entry, registry=registry)
        if not corrupt:
            stats["clean"] += 1
            continue

        stats["corrupt"] += 1
        stats[f"reason_{reason}"] += 1
        stats[f"locale_{entry.tgt_lang}"] += 1

        if verbose:
            print(
                f"  [{action.upper()}] {entry.tgt_lang:5s} | "
                f"{entry.source_text[:40]!r:42s} -> {entry.translation[:40]!r} ({reason})"
            )

        if action == "overwrite":
            to_overwrite.append(entry)
        elif action == "correct":
            corrected_value = registry.lookup(entry.source_text.strip(), entry.tgt_lang)
            to_correct.append((entry, corrected_value))
        else:
            to_delete.append(entry)

        if len(to_overwrite) + len(to_delete) + len(to_correct) >= max_changes:
            print(f"  WARNING: max_changes={max_changes} reached — stopping scan early.")
            break

    stats["to_overwrite"] = len(to_overwrite)
    stats["to_delete"] = len(to_delete)
    stats["to_correct"] = len(to_correct)

    if apply:
        print(
            f"\nApplying {len(to_overwrite)} overwrites, {len(to_delete)} deletes, "
            f"and {len(to_correct)} i18n-table corrections..."
        )

        for entry in to_overwrite:
            try:
                tm.store(
                    site_id=entry.site_id,
                    src_lang=entry.src_lang,
                    tgt_lang=entry.tgt_lang,
                    text=entry.source_text,
                    translation=entry.source_text,  # identity mapping
                    overwrite=True,
                )
                stats["overwritten"] += 1
            except Exception as e:
                print(f"  ERROR overwriting {entry.source_text[:30]!r}: {e}", file=sys.stderr)
                stats["overwrite_errors"] += 1

        for entry, corrected_value in to_correct:
            try:
                tm.store(
                    site_id=entry.site_id,
                    src_lang=entry.src_lang,
                    tgt_lang=entry.tgt_lang,
                    text=entry.source_text,
                    translation=corrected_value,
                    overwrite=True,
                )
                stats["corrected"] += 1
            except Exception as e:
                print(f"  ERROR correcting {entry.source_text[:30]!r}: {e}", file=sys.stderr)
                stats["correct_errors"] += 1

        for entry in to_delete:
            try:
                tm.delete(
                    site_id=entry.site_id,
                    src_lang=entry.src_lang,
                    tgt_lang=entry.tgt_lang,
                    text=entry.source_text,
                )
                stats["deleted"] += 1
            except Exception as e:
                print(f"  ERROR deleting {entry.source_text[:30]!r}: {e}", file=sys.stderr)
                stats["delete_errors"] += 1
    else:
        stats["overwritten"] = 0
        stats["deleted"] = 0

    return dict(stats)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surgical TM cleanup — scan and fix corrupt L2 entries"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report corrupt entries only (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply overwrites and deletes",
    )
    parser.add_argument(
        "--site",
        type=str,
        default=DEFAULT_SITE,
        help=f"Scope to this site_id (default: {DEFAULT_SITE})",
    )
    parser.add_argument(
        "--locales",
        type=str,
        help="Comma-separated target locales to restrict (default: all)",
    )
    parser.add_argument(
        "--max-changes",
        type=int,
        default=25000,
        help="Maximum entries to modify (safety cap, default: 25000)",
    )
    parser.add_argument(
        "--tm-path",
        type=Path,
        default=DEFAULT_TM_PATH,
        help=f"Path to L2 LMDB file (default: {DEFAULT_TM_PATH})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each corrupt entry",
    )
    args = parser.parse_args()

    apply = args.apply  # --apply overrides default dry-run

    tm_path = args.tm_path
    if not tm_path.exists():
        print(f"ERROR: TM path not found: {tm_path}", file=sys.stderr)
        sys.exit(1)

    only_locales = [l.strip() for l in args.locales.split(",")] if args.locales else None

    print(f"TM path: {tm_path}")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Max changes: {args.max_changes}")
    print()

    # Rule 4 (TC-HT-I18N-008): correct known template terms cached as an
    # untranslated passthrough, using the same reviewed i18n table the live
    # engine (TC-HT-I18N-004) and the content healer (TC-HT-I18N-007) both
    # consult — one canonical source, not a fourth copy of the answer.
    registry = TemplateStringRegistry()

    tm = L2PersistentTM(db_path=tm_path)
    stats = run(
        tm=tm,
        site=args.site,
        only_locales=only_locales,
        apply=apply,
        max_changes=args.max_changes,
        verbose=args.verbose,
        registry=registry,
    )

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Entries scanned:        {stats.get('scanned', 0):>8,}")
    print(f"Clean entries:          {stats.get('clean', 0):>8,}")
    print(f"Corrupt entries found:  {stats.get('corrupt', 0):>8,}")
    print(f"  identifier_translated:{stats.get('reason_identifier_translated', 0):>8,}")
    print(f"  artifact_in_translation:{stats.get('reason_artifact_in_translation', 0):>6,}")
    print(f"  heading_term_corrupted:{stats.get('reason_heading_term_corrupted', 0):>7,}")
    print(
        f"  heading_untranslated_passthrough:"
        f"{stats.get('reason_heading_untranslated_passthrough', 0):>4,}"
    )
    print(f"Planned overwrites:     {stats.get('to_overwrite', 0):>8,}")
    print(f"Planned deletes:        {stats.get('to_delete', 0):>8,}")
    print(f"Planned i18n corrections:{stats.get('to_correct', 0):>7,}")
    if apply:
        print(f"Overwrites applied:     {stats.get('overwritten', 0):>8,}")
        print(f"Deletes applied:        {stats.get('deleted', 0):>8,}")
        print(f"i18n corrections applied:{stats.get('corrected', 0):>7,}")
        print(f"Overwrite errors:       {stats.get('overwrite_errors', 0):>8,}")
        print(f"Delete errors:          {stats.get('delete_errors', 0):>8,}")
        print(f"Correction errors:      {stats.get('correct_errors', 0):>8,}")

    if not apply:
        print()
        print("DRY-RUN complete. Run with --apply to fix entries.")
    else:
        print()
        print("APPLY complete.")
        print(
            "Rollback: python scripts/tm/restore_tm.py --input data/tm/backups/backup_pre_cleanup.tar.gz"
        )


if __name__ == "__main__":
    main()
