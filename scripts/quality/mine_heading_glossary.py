"""mine_heading_glossary.py — mine candidate i18n table entries + protected-term
candidates from the already-translated corpus. READ-ONLY against the content
repo — never writes there.

Mission: heading-i18n-governance-20260723 (successor to HT-QUALITY-GATES-001),
taskcard TC-HT-I18N-002. See
C:\\Users\\prora\\.claude\\plans\\glittery-waddling-moth.md §5/§7 for the
root-cause analysis this feeds.

Extended by mission reference-i18n-hardening-20260725 (miner v2, plan item
B1) with:
  - a UNIVERSAL translated-vote rule (normalize(loc) != normalize(en))
    replacing the old ASCII-shape test, so Latin-script locales (es, de,
    fr, ...) can be mined -- the v1 rule treated every Latin-script
    translation as "still English" and mined nothing for 23 of the 36
    reference.aspose.org target locales.
  - an equal-count zip fast-path (the dominant case for generated docs)
    with the original two-pointer walk kept as the fallback for files
    whose heading counts differ.
  - three new tracks: table_headers (Track T), boilerplate (Track P),
    en_consistency (Track E, report-only).
  - a --from-discovery consumer that joins data/discovery/unresolved_terms
    .jsonl entries with corpus evidence (closes gap L2-002 -- that log had
    no downstream consumer).
  - identifier signals (multi_hump / matches_basename /
    matches_frontmatter_api / file_spread / family_spread) per heading
    term, to help the classification step distinguish page-specific
    identifiers from real i18n candidates.
  - --locales all reads target_langs from the site profile instead of the
    hardcoded 13-locale NON_LATIN_LOCALES list.

IMPORTANT (the es-"Revisión" lesson): vote share is EVIDENCE ONLY, never an
approval signal. A corpus majority can be confidently wrong -- on this exact
corpus, Spanish "Overview" resolves to "Revisión" (~90% vote share) in the
existing production data, and "Revisión" means "Review", not "Overview".
The old `meets_confidence_threshold` field (auto-confidence gating) has been
REMOVED from the output schema for this reason; approval is the separate,
linguistically-led adjudication workflow (plan item B3), which may OVERRIDE
the corpus majority. `top_share`/`n_samples` remain as evidence fields.

For every ASCII-shaped markdown heading found in the EN source corpus, this
walks each locale's counterpart file, aligns the two heading sequences, and
records every DISTINCT translation seen for that heading text in that
locale, with counts. No majority vote is auto-applied here -- that decision
belongs to the agentic adjudication step; this script only produces
evidence.

Output (under --out-dir, default data/glossary/):
  - heading_translation_candidates.json  (Track B: en_term/locale -> ranked
    list of {text, count}, plus identifier signals and top_share)
  - identifier_candidates.json           (Track C: en_term -> total
    occurrence count, for headings that rarely or never get a confident
    non-English translation in ANY locale -- i.e. look like real
    identifiers, not necessarily approved but flagged for review)
  - i18n_candidates_v2/table_headers.json     (Track T)
  - i18n_candidates_v2/boilerplate.json       (Track P)
  - i18n_candidates_v2/en_source_inconsistency.json  (Track E, report-only)
  - i18n_candidates_v2/discovery_derived_candidates.json  (--from-discovery only)

Usage:
  python scripts/quality/mine_heading_glossary.py --dry-run
  python scripts/quality/mine_heading_glossary.py --sites reference.aspose.org --locales ja,zh,ru --dry-run
  python scripts/quality/mine_heading_glossary.py --sites reference.aspose.org --locales all --tracks all
  python scripts/quality/mine_heading_glossary.py --from-discovery data/discovery/unresolved_terms.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parents[2]

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"
NON_LATIN_LOCALES = ["ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh"]
ALL_TRACKS = ["headings", "table_headers", "boilerplate", "en_consistency"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_ASCII_HEADING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]{1,30}$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:]*-{2,}[\s:|-]*\|?$")

# Minimum confirming samples + vote share: EVIDENCE fields only (recorded on
# every Track B/T candidate as `n_samples`/`top_share`). NOT an approval
# gate -- see module docstring's es-"Revisión" warning.
MIN_CONFIRMING_SAMPLES = 5
MIN_VOTE_SHARE = 0.80

# Boilerplate phrase templates (Track P), wording verified against the live
# reference.aspose.org corpus (en/pdf/net/*.md, en/3d/*/*.md samples) rather
# than assumed. The corpus is NOT perfectly consistent about these (Track E
# records the alternates, e.g. a longer "Browse the properties..." variant
# seen in some 3d/python files) -- these regexes match the DOMINANT shape
# only; non-matching "is a class/enum in ..." lines are counted separately
# as en_consistency evidence, not forced through this template.
# Platform text (".NET", "C++", "Python via .NET", ...) commonly CONTAINS a
# literal period itself, so it cannot be captured with a "no dot" character
# class -- `.+?` (non-greedy, any char) expands only as far as the next
# fixed literal requires, which correctly lands on the true platform text
# even when it embeds periods (confirmed against the live corpus's ".NET"/
# "C++" values).
_PLATFORM_CAPTURE = r"(?P<platform>.+?)"

_BOILERPLATE_TEMPLATES = [
    {
        "id": "phrase.inherits_from",
        "re": re.compile(r"^Inherits from: (?P<api>`[^`\n]+`)\.$", re.MULTILINE),
    },
    {
        "id": "phrase.is_a_class_in",
        "re": re.compile(
            rf"^(?P<api>`[^`\n]+`) is a class in Aspose\.(?P<family>\w+) FOSS for {_PLATFORM_CAPTURE}\.$",
            re.MULTILINE,
        ),
    },
    {
        "id": "phrase.is_an_enum_in",
        "re": re.compile(
            rf"^(?P<api>`[^`\n]+`) is a enum in Aspose\.(?P<family>\w+) FOSS for {_PLATFORM_CAPTURE}\.$",
            re.MULTILINE,
        ),
    },
    {
        "id": "phrase.is_an_interface_in",
        "re": re.compile(
            rf"^(?P<api>`[^`\n]+`) is a interface in Aspose\.(?P<family>\w+) FOSS for {_PLATFORM_CAPTURE}\.$",
            re.MULTILINE,
        ),
    },
    {
        "id": "phrase.is_a_struct_in",
        "re": re.compile(
            rf"^(?P<api>`[^`\n]+`) is a struct in Aspose\.(?P<family>\w+) FOSS for {_PLATFORM_CAPTURE}\.$",
            re.MULTILINE,
        ),
    },
    {
        "id": "phrase.class_provides_methods",
        "re": re.compile(
            rf"^This class provides (?P<n>\d+) methods? for working with "
            rf"(?P<api>`[^`\n]+`|[\w.]+) objects in {_PLATFORM_CAPTURE} programs\.$",
            re.MULTILINE,
        ),
    },
    {
        # Deliberately NOT end-anchored: the rest of this line is the
        # enum's OWN value list (page-specific data, not template text) --
        # only the fixed prefix up to "values:" is a reusable phrase.
        # `prefix_only` tells _mine_boilerplate to isolate just that prefix
        # in the locale line (split at the first backtick-quoted value)
        # rather than voting the whole, enum-specific line.
        "id": "phrase.enum_defines_values",
        "re": re.compile(r"^This enumeration defines (?P<n>\d+) values:", re.MULTILINE),
        "prefix_only": True,
    },
    {
        "id": "phrase.members_accessible_after_install",
        "re": re.compile(
            r"^All public members are accessible to any (?P<platform>.+?) application "
            r"after installing the Aspose\.(?P<family>\w+) FOSS for (?P=platform) package\.$",
            re.MULTILINE,
        ),
    },
]


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


def _target_langs_for_site(site: str) -> list[str]:
    """Read target_langs from config/site_profiles/<site>.yaml -- used by
    --locales all so mining covers every locale the site actually ships,
    not just the 13 hardcoded non-Latin ones."""
    import yaml

    profile_path = _REPO_ROOT / "config" / "site_profiles" / f"{site}.yaml"
    if not profile_path.exists():
        return list(NON_LATIN_LOCALES)
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    langs = data.get("target_langs") or []
    return [str(lang) for lang in langs]


def _get_body(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2] if len(parts) >= 3 else text


def _get_frontmatter(text: str) -> dict:
    """Best-effort YAML frontmatter parse for the matches_frontmatter_api
    identifier signal. Never raises -- a parse failure just means that
    signal is unavailable for this file, not a mining crash."""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml

        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _headings(text: str) -> list[str]:
    body = _get_body(text)
    return [m.group(2).strip() for m in _HEADING_RE.finditer(body)]


def _normalize_for_comparison(text: str) -> str:
    """Mining-only comparison normalization: NFC + casefold + whitespace
    collapse + trailing-colon strip. Deliberately looser than the resolver's
    normalize_for_registry() (case-SENSITIVE, colon-lossless) -- this
    function only decides "did translation happen at all" for vote
    detection; the resolver's stricter, case-sensitive lookup is what
    actually serves values at translation time."""
    t = unicodedata.normalize("NFC", text).strip()
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(":：").strip()
    return t.casefold()


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
    zip would silently drop every file where counts differ even slightly).

    Vote rule (reference-i18n-hardening-20260725, universal): a locale
    heading counts as "translated" iff its normalized form differs from the
    EN heading's normalized form -- works for any script, not just non-Latin
    ones. An EN heading is only ever considered a candidate if it is
    ASCII-heading-shaped (English source headings always are)."""
    j = 0
    n = len(locale_headings)
    for en_h in en_headings:
        if j >= n:
            break
        if _ASCII_HEADING_RE.match(en_h):
            identifier_occurrences[en_h] += 1
            loc_h = locale_headings[j]
            if _normalize_for_comparison(loc_h) != _normalize_for_comparison(en_h):
                # Translated (or at least different) -- record the vote and
                # consume this locale heading as "matched."
                heading_votes.setdefault(en_h, Counter())[loc_h] += 1
                j += 1
                continue
            # Still untranslated (identical, normalized) at this position --
            # don't consume it (it might align better with the NEXT en
            # heading if this one was itself a stray/dropped section), just
            # move the en-side pointer forward.
            continue
        # en_h isn't ASCII-shaped (already non-English or punctuation-only,
        # e.g. an enum value list) — try to consume one locale heading in
        # lockstep to keep the pointers loosely synced, but don't vote.
        j += 1


def _zip_align_and_vote(
    en_headings: list[str],
    locale_headings: list[str],
    heading_votes: dict[str, Counter],
    identifier_occurrences: Counter,
) -> None:
    """Equal-count fast path: strict positional zip. Generated reference
    pages overwhelmingly have identical heading counts between EN and its
    locale counterpart (same generator skeleton, no dropped sections), so
    this is the common case; the two-pointer walk above is the fallback for
    the minority of files where counts differ."""
    for en_h, loc_h in zip(en_headings, locale_headings):
        if _ASCII_HEADING_RE.match(en_h):
            identifier_occurrences[en_h] += 1
            if _normalize_for_comparison(loc_h) != _normalize_for_comparison(en_h):
                heading_votes.setdefault(en_h, Counter())[loc_h] += 1


def _mine_heading_pair(
    en_headings: list[str],
    locale_headings: list[str],
    heading_votes: dict[str, Counter],
    identifier_occurrences: Counter,
    alignment_stats: Counter,
) -> None:
    """Dispatch to the equal-count fast path or the two-pointer fallback,
    and record which one fired (alignment_stats["equal"]/["unequal"]) --
    a per-locale misaligned-file counter is itself a defect signal (a
    locale tree with many count-mismatched files may indicate dropped
    sections or a stale/partial regeneration)."""
    if len(en_headings) == len(locale_headings):
        alignment_stats["equal"] += 1
        _zip_align_and_vote(en_headings, locale_headings, heading_votes, identifier_occurrences)
    else:
        alignment_stats["unequal"] += 1
        _align_and_vote(en_headings, locale_headings, heading_votes, identifier_occurrences)


def _table_header_rows(text: str) -> list[list[str]]:
    """Extract every pipe-table header row (the row immediately followed by
    a `|---|`-shaped separator line) as a list of stripped cell strings."""
    body = _get_body(text)
    lines = body.splitlines()
    rows = []
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        nxt = lines[i + 1].strip()
        if line.startswith("|") and _TABLE_SEP_RE.match(nxt):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)
    return rows


def _mine_table_headers(
    en_text: str,
    tr_text: str,
    cell_votes: dict[str, Counter],
    row_votes: dict[tuple, Counter],
    cell_identifier_occ: Counter,
    misaligned_tables: Counter,
) -> None:
    """Track T: table header rows. Tables are aligned by INDEX within the
    file (generated docs emit tables in a fixed skeleton order) -- when an
    EN/locale table pair has an equal cell count, vote per column token;
    the full row is ALSO recorded as a row-shape variant regardless of
    per-cell alignment, so a wholesale MT hallucination (e.g. the observed
    German `Name der Person | Typ der` row) is caught even when individual
    cells wouldn't align 1:1."""
    en_rows = _table_header_rows(en_text)
    tr_rows = _table_header_rows(tr_text)
    for en_row, tr_row in zip(en_rows, tr_rows):
        row_votes.setdefault(tuple(en_row), Counter())[tuple(tr_row)] += 1
        if len(en_row) != len(tr_row):
            misaligned_tables["cell_count_mismatch"] += 1
            continue
        for en_cell, tr_cell in zip(en_row, tr_row):
            if not _ASCII_HEADING_RE.match(en_cell):
                continue
            cell_identifier_occ[en_cell] += 1
            if _normalize_for_comparison(tr_cell) != _normalize_for_comparison(en_cell):
                cell_votes.setdefault(en_cell, Counter())[tr_cell] += 1
    if len(en_rows) != len(tr_rows):
        misaligned_tables["table_count_mismatch"] += 1


def _prose_lines(text: str) -> list[str]:
    """Body LINES that are prose (not headings, not table rows, not bullet
    list items, not blank) -- the candidate pool for boilerplate-sentence
    alignment. One entry per physical line, in document order. Line-level
    (not paragraph-level): the real corpus packs multiple distinct
    boilerplate sentences into a single blank-line-delimited paragraph
    block (e.g. the "is a class in ..." and "Inherits from: ..." sentences
    are adjacent single-newline-joined lines, confirmed against a live
    en/pdf/net/*.md sample) -- paragraph-level matching would only ever
    test the first line of such a block."""
    body = _get_body(text)
    out = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("-"):
            continue
        out.append(stripped)
    return out


def _mine_boilerplate(
    en_text: str,
    tr_text: str,
    phrase_votes: dict[str, Counter],
    placeholder_corruption: Counter,
) -> None:
    """Track P: parameterized boilerplate. EN prose lines and locale prose
    lines are matched by INDEX within each document's prose-line list (the
    same "fixed generator skeleton" assumption as table/heading alignment)
    -- a locale line is only accepted as evidence if every captured EN
    token (identifiers, counts, family/platform names -- all values this
    mission's DO_NOT_TRANSLATE rules say must survive verbatim) still
    appears literally in it; otherwise it's recorded as
    placeholder_corruption (real evidence: a template whose parametrized
    slots got corrupted/translated by MT) rather than a false vote."""
    en_lines = _prose_lines(en_text)
    tr_lines = _prose_lines(tr_text)
    for idx, en_line in enumerate(en_lines):
        if idx >= len(tr_lines):
            break
        tr_line = tr_lines[idx]
        for template in _BOILERPLATE_TEMPLATES:
            m = template["re"].match(en_line)
            if not m:
                continue
            tokens = m.groupdict()
            missing = [v for v in tokens.values() if v and v not in tr_line]
            if missing:
                placeholder_corruption[template["id"]] += 1
                continue
            if template.get("prefix_only"):
                # The remainder of this line is page-specific data (e.g. an
                # enum's own value list), not template text -- isolate just
                # the fixed prefix at the first backtick-quoted value.
                cut = tr_line.find("`")
                candidate_source = tr_line[:cut].strip() if cut != -1 else tr_line
            else:
                candidate_source = tr_line
            candidate = candidate_source
            for token, value in tokens.items():
                if value:
                    candidate = candidate.replace(value, "{" + token + "}")
            phrase_votes.setdefault(template["id"], Counter())[candidate] += 1
            break  # one template match per line


def _en_consistency_signals(en_text: str, stats: dict) -> None:
    """Track E (report-only): EN-source inconsistency evidence -- table
    header row-shape distribution and non-dominant "is a X in ..."
    boilerplate variants. Handed off as-is to the generator owner; this
    mission does not normalize the EN source."""
    for row in _table_header_rows(en_text):
        stats["row_shapes"][tuple(row)] += 1
    body = _get_body(en_text)
    for line in body.splitlines():
        line = line.strip()
        if re.match(r"^`[^`]+` is an? \w+ in ", line):
            matched_dominant = any(
                t["re"].match(line)
                for t in _BOILERPLATE_TEMPLATES
                if t["id"].startswith("phrase.is_a") or t["id"].startswith("phrase.is_an")
            )
            if not matched_dominant:
                stats["alternate_is_a_templates"][line[:120]] += 1


def _identifier_signals_for_term(
    term: str,
    file_occurrences: dict[str, set],
    family_occurrences: dict[str, set],
) -> dict:
    from src.translation_engine.terminology.classification import _MULTI_HUMP_RE

    files = file_occurrences.get(term, set())
    families = family_occurrences.get(term, set())
    return {
        "multi_hump": bool(_MULTI_HUMP_RE.match(term)),
        "file_spread": len(files),
        "family_spread": len(families),
    }


def _load_discovery_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _run_discovery_consumer(discovery_path: Path, out_dir: Path) -> None:
    """--from-discovery: aggregate data/discovery/unresolved_terms.jsonl
    (classification.py's continuous single-hump-word discovery log, which
    had no consumer before this mission -- gap L2-002) into a candidate
    queue joinable with corpus mining evidence. Does not itself decide
    anything -- output feeds the same adjudication workflow as the other
    tracks."""
    records = _load_discovery_log(discovery_path)
    agg: dict[str, dict] = {}
    for rec in records:
        term = rec.get("term")
        if not term:
            continue
        entry = agg.setdefault(term, {"term": term, "count": 0, "locales": set(), "contexts": set()})
        entry["count"] += 1
        if rec.get("locale"):
            entry["locales"].add(rec["locale"])
        if rec.get("context"):
            entry["contexts"].add(rec["context"])
    candidates = [
        {
            "term": v["term"],
            "count": v["count"],
            "locales": sorted(v["locales"]),
            "contexts": sorted(v["contexts"]),
            "source": "discovery",
        }
        for v in agg.values()
    ]
    candidates.sort(key=lambda r: (-r["count"], r["term"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "discovery_derived_candidates.json"
    out_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Discovery log: {len(records)} raw lines -> {len(candidates)} distinct terms -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine heading/table-header/boilerplate translation candidates "
        "and identifier candidates from the already-translated corpus (read-only)."
    )
    parser.add_argument("--sites", type=str, default="reference.aspose.org")
    parser.add_argument("--locales", type=str, default="")
    parser.add_argument("--out-dir", type=str, default="data/glossary")
    parser.add_argument(
        "--tracks",
        type=str,
        default="headings",
        help="Comma list of: headings,table_headers,boilerplate,en_consistency,all",
    )
    parser.add_argument(
        "--sample-per-locale",
        type=int,
        default=0,
        help="Cap EN/locale file pairs scanned per locale (0 = unlimited, deterministic: sorted paths, first N)",
    )
    parser.add_argument(
        "--from-discovery",
        type=str,
        default="",
        help="Path to data/discovery/unresolved_terms.jsonl to aggregate into a candidate queue (standalone mode)",
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)

    if args.from_discovery:
        _run_discovery_consumer(Path(args.from_discovery), out_dir / "i18n_candidates_v2")
        return

    sites = ALL_SITES if args.sites.strip().lower() == "all" else [
        s.strip() for s in args.sites.split(",") if s.strip()
    ]
    tracks = (
        list(ALL_TRACKS)
        if args.tracks.strip().lower() == "all"
        else [t.strip() for t in args.tracks.split(",") if t.strip()]
    )
    unknown_tracks = set(tracks) - set(ALL_TRACKS)
    if unknown_tracks:
        raise SystemExit(f"Unknown --tracks value(s): {sorted(unknown_tracks)}; valid: {ALL_TRACKS}")

    out_dir.mkdir(parents=True, exist_ok=True)
    v2_dir = out_dir / "i18n_candidates_v2"
    if any(t != "headings" for t in tracks):
        v2_dir.mkdir(parents=True, exist_ok=True)

    root = _resolve_content_root()
    print(f"Content root: {root}")
    print(f"Sites: {sites}")
    print(f"Tracks: {tracks}")

    # heading_votes[locale][en_term] = Counter(translation -> count)
    per_locale_votes: dict[str, dict[str, Counter]] = defaultdict(dict)
    per_locale_identifier_occ: dict[str, Counter] = defaultdict(Counter)
    per_locale_alignment: dict[str, Counter] = defaultdict(Counter)
    # Track T accumulators (locale-independent key space: cell/row text is
    # compared per locale but stored flat since table_headers.json is keyed
    # like Track B: {en_cell, locale, candidates}).
    per_locale_cell_votes: dict[str, dict[str, Counter]] = defaultdict(dict)
    per_locale_row_votes: dict[str, dict[tuple, Counter]] = defaultdict(dict)
    per_locale_cell_identifier_occ: dict[str, Counter] = defaultdict(Counter)
    per_locale_misaligned_tables: dict[str, Counter] = defaultdict(Counter)
    # Track P accumulators.
    per_locale_phrase_votes: dict[str, dict[str, Counter]] = defaultdict(dict)
    per_locale_placeholder_corruption: dict[str, Counter] = defaultdict(Counter)
    # Track E (EN-only, not per-locale).
    en_consistency_stats = {"row_shapes": Counter(), "alternate_is_a_templates": Counter()}
    # Identifier signals (EN-side, not per-locale).
    term_file_occurrences: dict[str, set] = defaultdict(set)
    term_family_occurrences: dict[str, set] = defaultdict(set)

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

        if args.locales.strip().lower() == "all":
            locales = _target_langs_for_site(site)
        elif args.locales:
            locales = [loc.strip() for loc in args.locales.split(",") if loc.strip()]
        else:
            locales = list(NON_LATIN_LOCALES)  # backward-compatible default

        en_files = sorted(en_root.rglob("*.md"))
        print(f"Site: {site} ({len(en_files)} EN files) locales={locales}")

        if "en_consistency" in tracks:
            for en_path in en_files:
                try:
                    en_text = en_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                _en_consistency_signals(en_text, en_consistency_stats)

        if "headings" in tracks or "table_headers" in tracks or "boilerplate" in tracks:
            for en_path in en_files:
                try:
                    en_text = en_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel = en_path.relative_to(en_root)
                family = rel.parts[0] if rel.parts else ""
                for h in _headings(en_text):
                    if _ASCII_HEADING_RE.match(h):
                        term_file_occurrences[h].add(str(rel))
                        term_family_occurrences[h].add(family)

        for locale in locales:
            locale_root = site_root / locale
            if not locale_root.exists():
                continue
            votes = per_locale_votes[locale]
            identifier_occ = per_locale_identifier_occ[locale]
            alignment_stats = per_locale_alignment[locale]
            cell_votes = per_locale_cell_votes[locale]
            row_votes = per_locale_row_votes[locale]
            cell_identifier_occ = per_locale_cell_identifier_occ[locale]
            misaligned_tables = per_locale_misaligned_tables[locale]
            phrase_votes = per_locale_phrase_votes[locale]
            placeholder_corruption = per_locale_placeholder_corruption[locale]

            candidate_files = en_files
            if args.sample_per_locale:
                candidate_files = en_files[: args.sample_per_locale]

            n_pairs = 0
            for en_path in candidate_files:
                rel = en_path.relative_to(en_root)
                tr_path = locale_root / rel
                if not tr_path.exists():
                    continue
                try:
                    en_text = en_path.read_text(encoding="utf-8", errors="replace")
                    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                if "headings" in tracks:
                    en_h = _headings(en_text)
                    tr_h = _headings(tr_text)
                    if en_h and tr_h:
                        _mine_heading_pair(en_h, tr_h, votes, identifier_occ, alignment_stats)

                if "table_headers" in tracks:
                    _mine_table_headers(
                        en_text, tr_text, cell_votes, row_votes, cell_identifier_occ, misaligned_tables
                    )

                if "boilerplate" in tracks:
                    _mine_boilerplate(en_text, tr_text, phrase_votes, placeholder_corruption)

                n_pairs += 1
            files_scanned_total += n_pairs
            print(f"  {locale}: {n_pairs} EN/locale file pairs scanned", flush=True)

    # ------------------------------------------------------------------
    # Track B: heading translation candidates.
    # ------------------------------------------------------------------
    track_b = []
    strong_terms_by_locale: dict[str, set[str]] = defaultdict(set)
    all_locales_seen = sorted(per_locale_votes.keys())
    if "headings" in tracks:
        for locale, votes in per_locale_votes.items():
            for en_term, counter in votes.items():
                total = sum(counter.values())
                candidates = [{"text": text, "count": count} for text, count in counter.most_common()]
                top_count = candidates[0]["count"] if candidates else 0
                share = top_count / total if total else 0.0
                strong = total >= MIN_CONFIRMING_SAMPLES and share >= MIN_VOTE_SHARE
                ascii_leak = bool(candidates) and locale in NON_LATIN_LOCALES and _ASCII_HEADING_RE.match(
                    candidates[0]["text"]
                )
                if strong:
                    strong_terms_by_locale[locale].add(en_term)
                signals = _identifier_signals_for_term(
                    en_term, term_file_occurrences, term_family_occurrences
                )
                track_b.append(
                    {
                        "en_term": en_term,
                        "locale": locale,
                        "candidates": candidates,
                        "n_samples": total,
                        "top_share": round(share, 4),
                        # EVIDENCE ONLY -- see module docstring. Never an
                        # approval gate.
                        "strong_evidence": strong,
                        "ascii_vote_in_nonlatin_locale": bool(ascii_leak),
                        "identifier_signals": signals,
                    }
                )
        track_b.sort(key=lambda r: (-r["n_samples"], r["en_term"], r["locale"]))

        all_terms = set()
        for identifier_occ in per_locale_identifier_occ.values():
            all_terms.update(identifier_occ.keys())

        track_c = []
        for term in sorted(all_terms):
            total_occ = sum(occ.get(term, 0) for occ in per_locale_identifier_occ.values())
            strong_in_any_locale = any(term in strong_terms_by_locale[loc] for loc in all_locales_seen)
            if not strong_in_any_locale:
                signals = _identifier_signals_for_term(
                    term, term_file_occurrences, term_family_occurrences
                )
                track_c.append(
                    {"en_term": term, "total_occurrences": total_occ, "identifier_signals": signals}
                )
        track_c.sort(key=lambda r: (-r["total_occurrences"], r["en_term"]))

        heading_out = out_dir / "heading_translation_candidates.json"
        identifier_out = out_dir / "identifier_candidates.json"
        heading_out.write_text(json.dumps(track_b, ensure_ascii=False, indent=2), encoding="utf-8")
        identifier_out.write_text(json.dumps(track_c, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTrack B (heading) candidates: {len(track_b)} -> {heading_out}")
        print(f"Track C (identifier) candidates: {len(track_c)} -> {identifier_out}")
        print("\nTop 10 Track B candidates by sample count:")
        for row in track_b[:10]:
            top = row["candidates"][0] if row["candidates"] else None
            top_text = repr(top["text"]) if top else "None"
            print(
                f"  {row['en_term']!r:20s} [{row['locale']}] n={row['n_samples']:5d} "
                f"top={top_text} top_share={row['top_share']}"
            )
        print("\nAlignment mode counts per locale (equal=zip fast-path, unequal=two-pointer fallback):")
        for locale in sorted(per_locale_alignment.keys()):
            stats = per_locale_alignment[locale]
            print(f"  {locale}: equal={stats['equal']} unequal={stats['unequal']}")

    # ------------------------------------------------------------------
    # Track T: table header rows.
    # ------------------------------------------------------------------
    if "table_headers" in tracks:
        track_t = []
        for locale, cell_votes in per_locale_cell_votes.items():
            for en_cell, counter in cell_votes.items():
                total = sum(counter.values())
                candidates = [{"text": text, "count": count} for text, count in counter.most_common()]
                top_count = candidates[0]["count"] if candidates else 0
                share = top_count / total if total else 0.0
                ascii_leak = bool(candidates) and locale in NON_LATIN_LOCALES and _ASCII_HEADING_RE.match(
                    candidates[0]["text"]
                )
                track_t.append(
                    {
                        "en_cell": en_cell,
                        "locale": locale,
                        "candidates": candidates,
                        "n_samples": total,
                        "top_share": round(share, 4),
                        "ascii_vote_in_nonlatin_locale": bool(ascii_leak),
                    }
                )
        track_t.sort(key=lambda r: (-r["n_samples"], r["en_cell"], r["locale"]))

        track_t_rows = []
        for locale, row_votes in per_locale_row_votes.items():
            for en_row, counter in row_votes.items():
                total = sum(counter.values())
                candidates = [
                    {"row": list(row), "count": count} for row, count in counter.most_common()
                ]
                track_t_rows.append(
                    {
                        "en_row": list(en_row),
                        "locale": locale,
                        "candidates": candidates,
                        "n_samples": total,
                        "misaligned": dict(per_locale_misaligned_tables.get(locale, {})),
                    }
                )
        track_t_rows.sort(key=lambda r: (-r["n_samples"], r["en_row"], r["locale"]))

        table_out = v2_dir / "table_headers.json"
        table_out.write_text(
            json.dumps({"cells": track_t, "rows": track_t_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nTrack T (table header) cell candidates: {len(track_t)}, row shapes: {len(track_t_rows)} -> {table_out}")

    # ------------------------------------------------------------------
    # Track P: parameterized boilerplate.
    # ------------------------------------------------------------------
    if "boilerplate" in tracks:
        track_p = []
        for locale, phrase_votes in per_locale_phrase_votes.items():
            for template_id, counter in phrase_votes.items():
                total = sum(counter.values())
                candidates = [{"template": text, "count": count} for text, count in counter.most_common()]
                track_p.append(
                    {
                        "template_id": template_id,
                        "locale": locale,
                        "candidates": candidates,
                        "n_samples": total,
                        "placeholder_corruption": per_locale_placeholder_corruption.get(
                            locale, Counter()
                        ).get(template_id, 0),
                    }
                )
        track_p.sort(key=lambda r: (-r["n_samples"], r["template_id"], r["locale"]))
        boilerplate_out = v2_dir / "boilerplate.json"
        boilerplate_out.write_text(json.dumps(track_p, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTrack P (boilerplate) candidates: {len(track_p)} -> {boilerplate_out}")

    # ------------------------------------------------------------------
    # Track E: EN-source inconsistency (report-only).
    # ------------------------------------------------------------------
    if "en_consistency" in tracks:
        en_out = v2_dir / "en_source_inconsistency.json"
        payload = {
            "row_shapes": [
                {"row": list(row), "count": count}
                for row, count in en_consistency_stats["row_shapes"].most_common()
            ],
            "alternate_is_a_templates": [
                {"excerpt": excerpt, "count": count}
                for excerpt, count in en_consistency_stats["alternate_is_a_templates"].most_common()
            ],
        }
        en_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTrack E (EN-source inconsistency, report-only): {len(payload['row_shapes'])} row shapes -> {en_out}")

    print(f"\nFiles scanned (EN/locale pairs, summed across locales): {files_scanned_total}")


if __name__ == "__main__":
    main()
