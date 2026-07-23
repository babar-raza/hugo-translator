"""Full-corpus scan for cross-locale content duplication: a translated
file's title/description/head_title is byte-identical to a DIFFERENT
locale's file for the same EN source, despite the two locales being
different target languages.

Root cause (found 2026-07-19 via direct agent investigation): a now-deleted,
never-committed one-off remediation script ran on 2026-07-13 and wrote one
locale's correctly-translated content to an adjacent locale's output path
(confirmed for 3 file groups: sk<-ru, fi<-fa, it<-he, all under
kb.aspose.org/slides/cpp/how-to-get-started-slides-cpp.md). The script no
longer exists (not in git history, not on disk) so there is no code to fix
-- this audit exists to find the FULL scope of that incident's damage,
which is unknown beyond the 3 groups directly verified.

Detection: for each EN source file, group all existing translated locale
files by their (title, description, head_title) field values. If 2+
DIFFERENT locales share the exact same non-trivial field value, that's a
near-certain duplication bug -- two genuinely different target languages
essentially never produce byte-identical non-trivial translated strings.

HT-QUALITY-GATES-001 Phase 8 (Tier B #6): the same detection now also
covers BODY paragraphs, not just frontmatter fields -- the Phase 7
reconnaissance's gap category "clean two-locale proof of shared batch/
template corruption" was reported as "no detector" specifically because
this script's original scope was frontmatter-field-only; a shared-batch
corruption that only affects body prose (not title/description) would
sail through unnoticed. Body paragraphs are matched as a flat, position-
independent set (unlike frontmatter fields, which are matched per named
key) -- paragraph order/count can legitimately differ across locales
(reflow, splitting), so any two locales sharing byte-identical prose
ANYWHERE in the body is the meaningful signal, not "at the same position."
Fenced code blocks are excluded (code is legitimately identical across
locales by design, not a bug) via the same fence_spans primitive
write_gate.py's new gates use (HT-QUALITY-GATES-001 Phase 8, F2).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.translation_engine.fence_spans import strip_fenced  # noqa: E402
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import (  # noqa: E402
    iter_locale_pairs,
    resolve_source_root,
)

_CONFIG = ConfigService(_PROJECT_ROOT / "config")
# Durable-fix consolidation: registry-driven site list (was a hardcoded
# 5-site list) + registry-driven discovery (was a hand-rolled
# BLOG_SCHEME_SITES special case + duplicate iter_groups_dir_scheme/
# iter_groups_blog_scheme pair) via src/utils/content_discovery.py.
SITES = _CONFIG.list_sites(autonomous_only=True)

FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
FIELDS_TO_CHECK = ["title", "description", "head_title", "subtitle", "head_description", "summary"]
MIN_LEN = 8  # ignore trivially short values (numbers, single words, brand-only)


def _load_translate_mode_fields(site: str) -> set[str]:
    """Fields explicitly configured with mode: translate for this site.
    Excludes both passthrough fields (e.g. reference.aspose.org's
    title/linkTitle, kept as the API identifier verbatim -- SUPPOSED to be
    identical across all locales) AND unconfigured fields (not in this
    site's frontmatter schema at all, e.g. reference.aspose.org has no
    "subtitle" rule -- these are never touched by the translation pipeline,
    so they're copied from EN untouched and are also expected to be
    identical, not a bug)."""
    path = _CONFIG.site_profiles_dir / f"{site}.yaml"
    with open(path, encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)
    fm_config = profile.get("frontmatter", {}) or {}
    result = set()
    for field in FIELDS_TO_CHECK:
        rule = fm_config.get(field)
        if rule is not None and rule.get("mode") == "translate":
            result.add(field)
    return result


def extract_fields(content: str, allowed_fields: set[str]) -> dict[str, str]:
    m = FM_RE.match(content)
    if not m:
        return {}
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    if not isinstance(fm, dict):
        return {}
    out = {}
    for field in allowed_fields:
        v = fm.get(field)
        if isinstance(v, str) and len(v.strip()) >= MIN_LEN:
            out[field] = v.strip()
    return out


# HT-QUALITY-GATES-001 Phase 8 (Tier B #6): body-paragraph min length is
# higher than frontmatter's MIN_LEN (8) -- short prose lines (a single
# short sentence, a common transitional phrase) are far more likely to
# legitimately coincide across two unrelated translations than a full
# paragraph is, so a higher floor keeps this check low-false-positive.
BODY_PARAGRAPH_MIN_LEN = 40
_BODY_PARA_FIELD_NAME = "body_paragraph"


def extract_body_paragraphs(content: str) -> list[str]:
    """Return non-trivial prose paragraphs from the body, excluding fenced
    code blocks (code is legitimately identical across locales by design,
    not a duplication bug)."""
    m = FM_RE.match(content)
    body = content[m.end():] if m else content
    body = strip_fenced(body)
    paragraphs = []
    for para in re.split(r"\n{2,}", body):
        stripped = para.strip()
        if len(stripped) >= BODY_PARAGRAPH_MIN_LEN:
            paragraphs.append(stripped)
    return paragraphs


def find_cross_locale_duplicates(
    field_values: dict[str, list[tuple[str, str]]],
) -> list[tuple[str, str, list[str]]]:
    """Pure grouping logic, factored out of scan() for testability without
    site-profile/content-root I/O. Given ``{field_name: [(locale, value),
    ...]}``, return ``[(field_name, value, distinct_locales_sharing_it), ...]``
    for every value shared by 2+ DISTINCT locales.

    Dedupes by distinct locale (HT-QUALITY-GATES-001 Phase 8, Tier B #6):
    a frontmatter field can only appear once per file, so this was
    previously a no-op safety net; body paragraphs can legitimately repeat
    WITHIN a single locale's own file (a different, already-covered bug --
    write_gate.py Gate 16 / duplicate_content), which must not be misread
    as 2 locales sharing content.
    """
    findings = []
    for field, pairs in field_values.items():
        by_value: dict[str, list[str]] = defaultdict(list)
        for locale, value in pairs:
            by_value[value].append(locale)
        for value, locales_sharing in by_value.items():
            distinct_locales = sorted(set(locales_sharing))
            if len(distinct_locales) >= 2:
                findings.append((field, value, distinct_locales))
    return findings


def iter_groups(site: str):
    """Yield (rel, [(locale, tr_path), ...]) grouping every EXISTING
    translated locale by its EN source file, for sources with 2+ existing
    translations. Registry-driven via content_discovery -- works
    identically for directory-scheme and file-suffix-scheme sites, no
    per-site branching."""
    try:
        profile = _CONFIG.get_site_profile(site)
    except Exception:
        return
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    if not content_root.exists():
        return

    source_root = resolve_source_root(profile, content_root)
    groups: dict[Path, list[tuple[str, Path]]] = defaultdict(list)
    for en_path, locale, tr_path in iter_locale_pairs(profile, content_root):
        if tr_path.exists():
            groups[en_path].append((locale, tr_path))

    for en_path, locale_files in groups.items():
        if len(locale_files) >= 2:
            rel = en_path.relative_to(source_root)
            yield str(rel), locale_files


def scan(output_path: str, sites: list[str]):
    results = []
    total_groups = 0
    total_findings = 0

    out_fh = open(output_path, "w", encoding="utf-8")
    print(f"Starting cross-locale duplication audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in sites:
        site_findings = 0
        site_groups = 0
        allowed_fields = _load_translate_mode_fields(site)
        iterator = iter_groups(site)

        for rel, locale_files in iterator:
            site_groups += 1
            total_groups += 1
            field_values: dict[str, list[tuple[str, str]]] = defaultdict(list)
            # HT-QUALITY-GATES-001 Phase 8 (Tier B #6): flat, position-
            # independent bucket -- every (locale, paragraph_text) pair
            # goes under the single synthetic "body_paragraph" field name,
            # since body prose isn't keyed like a frontmatter field.
            for locale, path in locale_files:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                fields = extract_fields(content, allowed_fields)
                for field, value in fields.items():
                    field_values[field].append((locale, value))
                for para in extract_body_paragraphs(content):
                    field_values[_BODY_PARA_FIELD_NAME].append((locale, para))

            for field, value, distinct_locales in find_cross_locale_duplicates(field_values):
                site_findings += 1
                total_findings += 1
                entry = {
                    "site": site,
                    "rel": rel,
                    "field": field,
                    "locales": distinct_locales,
                    "value_preview": value[:120],
                }
                out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                results.append(entry)

        print(f"{site}: {site_groups:,} multi-locale groups scanned, {site_findings} findings", flush=True)

    out_fh.close()

    print(f"\n=== SUMMARY ({total_groups:,} groups scanned, {total_findings} findings) ===")
    by_site = defaultdict(int)
    for e in results:
        by_site[e["site"]] += 1
    for site, count in sorted(by_site.items(), key=lambda x: -x[1]):
        print(f"  {site}: {count}")

    print("\n=== SAMPLE FINDINGS ===")
    for e in results[:20]:
        print(f"  [{e['site']}] {e['rel']} :: field={e['field']} locales={e['locales']}")

    return results


# ---------------------------------------------------------------------------
# HT-QUALITY-GATES-001 Phase 8 (Tier B #13): cross-entity content_hash
# collision -- the Phase 7 reconnaissance's own "unconfirmed root-cause
# candidate": two DIFFERENT EN source files sharing the same
# provenance.content_hash value. Distinct from write_gate.py Gate 32
# (_gate_content_hash_staleness), which only compares a SINGLE file's own
# EN-vs-translation hash for staleness -- this compares hashes ACROSS
# different EN source files, which no single-file gate can do (RC4: a
# gate only ever sees one translated file at a time).
# ---------------------------------------------------------------------------

_NESTED_FM_RE = FM_RE  # same frontmatter block regex, reused for clarity


def get_nested_field(content: str, *path: str) -> str | None:
    """Read a nested frontmatter field (e.g. provenance.content_hash)."""
    m = _NESTED_FM_RE.match(content)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    node = fm
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) else None


def find_content_hash_collisions(en_hash_map: dict[str, str]) -> dict[str, list[str]]:
    """Pure grouping: given ``{en_path_str: content_hash}``, return
    ``{content_hash: [en_path_str, ...]}`` for every hash shared by 2+
    DIFFERENT EN source files.
    """
    by_hash: dict[str, list[str]] = defaultdict(list)
    for en_path, h in en_hash_map.items():
        by_hash[h].append(en_path)
    return {h: sorted(paths) for h, paths in by_hash.items() if len(paths) >= 2}


def scan_content_hash_collisions(output_path: str, sites: list[str]) -> list[dict]:
    """Full-corpus scan: group EN source files per site by
    provenance.content_hash; for each colliding group, additionally check
    whether any single locale's translated output is byte-identical across
    the colliding EN sources -- the stronger confirmation signal that
    content was actually cross-served between unrelated pages, not just a
    coincidentally-duplicated EN source hash (e.g. two pages legitimately
    generated from the same upstream template revision).
    """
    results: list[dict] = []
    out_fh = open(output_path, "w", encoding="utf-8")
    print(f"Starting content-hash collision audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in sites:
        try:
            profile = _CONFIG.get_site_profile(site)
        except Exception:
            continue
        content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
        if not content_root.exists():
            continue
        source_root = resolve_source_root(profile, content_root)

        en_hash_map: dict[str, str] = {}
        en_content_cache: dict[str, str] = {}
        seen_en: set[Path] = set()
        for en_path, _locale, _tr_path in iter_locale_pairs(profile, content_root):
            if en_path in seen_en:
                continue
            seen_en.add(en_path)
            try:
                en_content = en_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            h = get_nested_field(en_content, "provenance", "content_hash")
            if h:
                rel = str(en_path.relative_to(source_root))
                en_hash_map[rel] = h
                en_content_cache[rel] = en_content

        collisions = find_content_hash_collisions(en_hash_map)
        site_findings = 0
        for content_hash, colliding_rels in collisions.items():
            entry = {
                "site": site,
                "content_hash": content_hash,
                "en_files": colliding_rels,
                "confirmed_translated_match": False,
            }
            # Second-stage confirmation: do any 2 of the colliding EN files
            # ALSO have byte-identical translated output for the same
            # locale? Only checked when the collision group is small enough
            # to be cheap (avoids O(n^2) blowup on a pathological hash with
            # many colliding sources, which would itself be a data-quality
            # anomaly worth flagging separately, not exhaustively cross-
            # checked here).
            if 2 <= len(colliding_rels) <= 5:
                tr_texts: dict[str, dict[str, str]] = {}  # locale -> {rel: text}
                for rel in colliding_rels:
                    en_path = source_root / rel
                    for _en, locale, tr_path in iter_locale_pairs(profile, content_root):
                        if str(_en.relative_to(source_root)) != rel or not tr_path.exists():
                            continue
                        try:
                            tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            continue
                        tr_texts.setdefault(locale, {})[rel] = tr_content
                for locale, by_rel in tr_texts.items():
                    values = list(by_rel.values())
                    if len(values) >= 2 and len(set(values)) < len(values):
                        entry["confirmed_translated_match"] = True
                        entry["confirmed_locale"] = locale
                        break

            out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            results.append(entry)
            site_findings += 1

        print(f"{site}: {len(en_hash_map):,} EN files hashed, {site_findings} hash collisions", flush=True)

    out_fh.close()
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=SITES)
    ap.add_argument("--output", default="data/audit/audit_cross_locale_duplication.jsonl")
    ap.add_argument(
        "--content-hash-collisions",
        action="store_true",
        help="Run the Tier B #13 cross-entity content_hash collision scan instead of the default cross-locale-duplication scan",
    )
    ap.add_argument(
        "--content-hash-output",
        default="data/audit/audit_content_hash_collision.jsonl",
    )
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    if args.content_hash_collisions:
        scan_content_hash_collisions(args.content_hash_output, args.sites)
    else:
        scan(args.output, args.sites)
