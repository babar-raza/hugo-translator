"""Full-corpus scan for the digit-prefixed-heading bug (found + fixed
2026-07-19, text_unit_extractor.py:1996): any non-Latin-locale heading that
starts with a digit and was left untranslated in English, because the old
"version number" regex had no end anchor and matched any string merely
STARTING with a digit (e.g. "3D Model Inspection and Validation").

Only checks non-Latin locales (script mismatch makes English-vs-translated
unambiguous without needing the EN source for comparison -- a Latin-script
locale leaving "3D Model..." in English is not detectable this way, but
non-Latin locales cover a large, clearly-identifiable slice of the damage).

Durable-fix consolidation: site/locale/file discovery is now registry-driven
via src/utils/content_discovery.py (reads each site's
output_layout.per_language_folders), replacing the previous hand-rolled
BLOG_SCHEME_SITES special case + duplicate iter_files_dirscheme/
iter_files_blogscheme pair. SITES is derived from the site-profile registry
(config/site_profiles/*.yaml via ConfigService.list_sites) instead of a
hardcoded 5-site list, so this now covers all real production sites.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import (  # noqa: E402
    iter_locale_pairs,
    resolve_source_root,
)

_CONFIG = ConfigService(_PROJECT_ROOT / "config")
SITES = _CONFIG.list_sites(autonomous_only=True)
NON_LATIN = {"ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "zh"}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
DIGIT_START_RE = re.compile(r"^\d")
ASCII_HEADING_RE = re.compile(r"^[\x00-\x7F]+$")


def get_body(content: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n?", content, re.S)
    return content[m.end():] if m else content


def check_file(tr_content: str) -> list[tuple[str, str]]:
    findings = []
    body = get_body(tr_content)
    in_code = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        heading_text = m.group(2).strip().strip("*").strip()
        if not heading_text or not DIGIT_START_RE.match(heading_text):
            continue
        if len(heading_text) < 6:
            continue  # avoid flagging short numeric-only headings like "3D" itself
        if ASCII_HEADING_RE.match(heading_text):
            findings.append(("digit_heading_untranslated", heading_text[:120]))
    return findings


def iter_translated_files(site: str):
    """Yield (locale, rel, tr_path) for existing non-Latin-locale translated
    files. Registry-driven via content_discovery -- works identically for
    directory-scheme and file-suffix-scheme sites, no per-site branching."""
    try:
        profile = _CONFIG.get_site_profile(site)
    except Exception:
        return
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    if not content_root.exists():
        return
    source_root = resolve_source_root(profile, content_root)
    for en_path, locale, tr_path in iter_locale_pairs(profile, content_root):
        if locale not in NON_LATIN or not tr_path.exists():
            continue
        rel = en_path.relative_to(source_root)
        yield locale, str(rel), tr_path


def scan(output_path: str | None, sites: list[str] | None):
    results = defaultdict(int)
    examples = []
    total_files = 0
    total_findings = 0

    out_fh = open(output_path, "w", encoding="utf-8") if output_path else None
    print(f"Starting digit-heading audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        iterator = iter_translated_files(site)
        site_files = 0
        site_findings = 0

        for locale, rel, tr_path in iterator:
            site_files += 1
            total_files += 1
            if site_files % 10000 == 0:
                print(f"  {site}: {site_files:,} files scanned, {site_findings} findings so far", flush=True)
            try:
                tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            findings = check_file(tr_content)
            if not findings:
                continue
            results[site] += len(findings)
            site_findings += len(findings)
            total_findings += len(findings)
            entry = {"site": site, "locale": locale, "rel": rel, "tr_path": str(tr_path),
                      "issue": "digit_heading_untranslated", "headings": [f[1] for f in findings]}
            if out_fh:
                out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if len(examples) < 20:
                examples.append(entry)

        print(f"{site}: {site_files:,} files scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_files:,} non-Latin-locale files scanned, {total_findings} findings) ===")
    for site, count in results.items():
        print(f"  {site}: {count}")

    print("\n=== SAMPLE FINDINGS ===")
    for e in examples:
        print(f"  [{e['site']}/{e['locale']}] {e['rel']} :: {e['headings']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_digit_headings.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
