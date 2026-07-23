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
            for locale, path in locale_files:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                fields = extract_fields(content, allowed_fields)
                for field, value in fields.items():
                    field_values[field].append((locale, value))

            for field, pairs in field_values.items():
                by_value: dict[str, list[str]] = defaultdict(list)
                for locale, value in pairs:
                    by_value[value].append(locale)
                for value, locales_sharing in by_value.items():
                    if len(locales_sharing) >= 2:
                        site_findings += 1
                        total_findings += 1
                        entry = {
                            "site": site,
                            "rel": rel,
                            "field": field,
                            "locales": sorted(locales_sharing),
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=SITES)
    ap.add_argument("--output", default="data/audit/audit_cross_locale_duplication.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
