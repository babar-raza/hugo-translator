"""mine_heading_glossary.py — mine candidate i18n table entries + protected-term
candidates from the already-translated corpus. READ-ONLY against the content
repo — never writes there.

Mission: heading-i18n-governance-20260723 (successor to HT-QUALITY-GATES-001),
taskcard TC-HT-I18N-002. See
C:\\Users\\prora\\.claude\\plans\\glittery-waddling-moth.md §5/§7 for the
root-cause analysis this feeds.

For every ASCII-shaped markdown heading found in the EN source corpus, this
walks each non-Latin locale's counterpart file, aligns the two heading
sequences (a forward-only two-pointer alignment — robust to a locale file
having an extra/missing section here or there, unlike a strict positional
zip requiring identical heading counts), and records every DISTINCT
translation seen for that heading text in that locale, with counts. No
majority vote is auto-applied here — that decision belongs to the agentic
adjudication step (TC-HT-I18N-003); this script only produces evidence.

Output: two JSON candidate queues under --out-dir (default data/glossary/):
  - heading_translation_candidates.json  (Track B: en_term/locale -> ranked
    list of {text, count})
  - identifier_candidates.json           (Track C: en_term -> total
    occurrence count, for headings that rarely or never get a confident
    non-ASCII translation — i.e. look like real identifiers)

Usage:
  python scripts/quality/mine_heading_glossary.py --dry-run
  python scripts/quality/mine_heading_glossary.py --sites reference.aspose.org --locales ja,zh,ru --dry-run
  python scripts/quality/mine_heading_glossary.py --sites all --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"
NON_LATIN_LOCALES = ["ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_ASCII_HEADING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{1,30}$")

# Minimum confirming samples + vote share for a Track B candidate to be
# considered strong enough to hand to the agentic review Workflow at all
# (weaker candidates still get recorded, just ranked lower / flagged).
MIN_CONFIRMING_SAMPLES = 5
MIN_VOTE_SHARE = 0.80


def _resolve_content_root() -> Path:
    """Same env-var/fallback pattern as heal_english_headings.py, extended
    to also check ASPOSE_ORG_CONTENT_REPO (the name actually set in this
    environment) ahead of the older ASPOSE_ORG_CONTENT convention."""
    for var in ("ASPOSE_ORG_CONTENT_REPO", "ASPOSE_ORG_CONTENT"):
        env = os.environ.get(var)
        if env:
            p = Path(env)
            if p.exists():
                return p
    for p in [
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
    ]:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot find content root. Set ASPOSE_ORG_CONTENT_REPO or ASPOSE_ORG_CONTENT."
    )


def _get_body(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2] if len(parts) >= 3 else text


def _headings(text: str) -> list[str]:
    body = _get_body(text)
    return [m.group(2).strip() for m in _HEADING_RE.finditer(body)]


def _align_and_vote(
    en_headings: list[str],
    locale_headings: list[str],
    heading_votes: dict[str, Counter],
    identifier_occurrences: Counter,
) -> None:
    """Forward-only two-pointer alignment: walk EN headings in order, and
    for each, advance a locale-side pointer looking for its counterpart.
    This tolerates a locale file having an extra/missing section without
    requiring len(en_headings) == len(locale_headings) (a strict positional
    zip would silently drop every file where counts differ even slightly)."""
    j = 0
    n = len(locale_headings)
    for en_h in en_headings:
        if j >= n:
            break
        if _ASCII_HEADING_RE.match(en_h):
            identifier_occurrences[en_h] += 1
            loc_h = locale_headings[j]
            if not _ASCII_HEADING_RE.match(loc_h):
                # Locale heading was actually translated — record the vote
                # and consume this locale heading as "matched."
                heading_votes.setdefault(en_h, Counter())[loc_h] += 1
                j += 1
                continue
            # Both ASCII — locale heading still untranslated at this
            # position; don't consume it (it might align better with the
            # NEXT en heading if this one was itself a stray/dropped
            # section), just move the en-side pointer forward.
            continue
        # en_h isn't ASCII-shaped (already non-English or punctuation-only,
        # e.g. an enum value list) — try to consume one locale heading in
        # lockstep to keep the pointers loosely synced, but don't vote.
        j += 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine heading-translation and identifier candidates from the "
        "already-translated corpus (read-only)."
    )
    parser.add_argument("--sites", type=str, default="reference.aspose.org")
    parser.add_argument("--locales", type=str, default="")
    parser.add_argument("--out-dir", type=str, default="data/glossary")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    sites = ALL_SITES if args.sites.strip().lower() == "all" else [
        s.strip() for s in args.sites.split(",") if s.strip()
    ]
    locales = (
        [loc.strip() for loc in args.locales.split(",") if loc.strip()]
        if args.locales
        else NON_LATIN_LOCALES
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    root = _resolve_content_root()
    print(f"Content root: {root}")
    print(f"Sites: {sites}")
    print(f"Locales: {locales}")
    print("(read-only — no writes to the content repo will be made)\n")

    # heading_votes[locale][en_term] = Counter(translation -> count)
    per_locale_votes: dict[str, dict[str, Counter]] = defaultdict(dict)
    per_locale_identifier_occ: dict[str, Counter] = defaultdict(Counter)
    files_scanned_total = 0

    for site in sites:
        site_root = root / site
        if not site_root.exists():
            print(f"  SKIP site {site} (not found)")
            continue
        en_root = site_root / EN_LOCALE
        if not en_root.exists():
            print(f"  SKIP site {site} (no en/ dir)")
            continue

        en_files = list(en_root.rglob("*.md"))
        print(f"Site: {site} ({len(en_files)} EN files)")

        for locale in locales:
            locale_root = site_root / locale
            if not locale_root.exists():
                continue
            votes = per_locale_votes[locale]
            identifier_occ = per_locale_identifier_occ[locale]
            n_pairs = 0
            for en_path in en_files:
                rel = en_path.relative_to(en_root)
                tr_path = locale_root / rel
                if not tr_path.exists():
                    continue
                try:
                    en_text = en_path.read_text(encoding="utf-8", errors="replace")
                    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                en_h = _headings(en_text)
                tr_h = _headings(tr_text)
                if not en_h or not tr_h:
                    continue
                _align_and_vote(en_h, tr_h, votes, identifier_occ)
                n_pairs += 1
            files_scanned_total += n_pairs
            print(f"  {locale}: {n_pairs} EN/locale file pairs scanned", flush=True)

    # Build Track B (translation) candidate queue.
    track_b = []
    strong_terms_by_locale: dict[str, set[str]] = defaultdict(set)
    for locale, votes in per_locale_votes.items():
        for en_term, counter in votes.items():
            total = sum(counter.values())
            candidates = [
                {"text": text, "count": count}
                for text, count in counter.most_common()
            ]
            top_count = candidates[0]["count"] if candidates else 0
            share = top_count / total if total else 0.0
            strong = total >= MIN_CONFIRMING_SAMPLES and share >= MIN_VOTE_SHARE
            if strong:
                strong_terms_by_locale[locale].add(en_term)
            track_b.append(
                {
                    "en_term": en_term,
                    "locale": locale,
                    "candidates": candidates,
                    "n_samples": total,
                    "meets_confidence_threshold": strong,
                }
            )
    track_b.sort(key=lambda r: -r["n_samples"])

    # Build Track C (identifier) candidate queue: terms that show up as an
    # ASCII heading often, but rarely/never get a confident translation in
    # ANY locale — these look like real class/type identifiers rather than
    # missed section headings.
    all_terms = set()
    for identifier_occ in per_locale_identifier_occ.values():
        all_terms.update(identifier_occ.keys())

    track_c = []
    for term in all_terms:
        total_occ = sum(occ.get(term, 0) for occ in per_locale_identifier_occ.values())
        strong_in_any_locale = any(term in strong_terms_by_locale[loc] for loc in locales)
        if not strong_in_any_locale:
            track_c.append({"en_term": term, "total_occurrences": total_occ})
    track_c.sort(key=lambda r: -r["total_occurrences"])

    heading_out = out_dir / "heading_translation_candidates.json"
    identifier_out = out_dir / "identifier_candidates.json"
    heading_out.write_text(json.dumps(track_b, ensure_ascii=False, indent=2), encoding="utf-8")
    identifier_out.write_text(json.dumps(track_c, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nFiles scanned (EN/locale pairs): {files_scanned_total}")
    print(f"Track B (translation) candidates: {len(track_b)} -> {heading_out}")
    print(f"Track C (identifier) candidates: {len(track_c)} -> {identifier_out}")
    print("\nTop 10 Track B candidates by sample count:")
    for row in track_b[:10]:
        top = row["candidates"][0] if row["candidates"] else None
        top_text = repr(top["text"]) if top else "None"
        print(
            f"  {row['en_term']!r:20s} [{row['locale']}] n={row['n_samples']:5d} "
            f"top={top_text} strong={row['meets_confidence_threshold']}"
        )


if __name__ == "__main__":
    main()
