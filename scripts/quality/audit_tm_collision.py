"""Full-corpus scan for TM key collision: a translated file's `description`/
`summary` frontmatter field names a DIFFERENT class/enum/interface than the
file itself is about.

Root cause (DELIVERABLE 53, fixed 2026-07-17 for NEW translations via the
tm_key_text fix): the TM key was derived from placeholder-protected text, so
two files sharing an identical template after their class name is masked
(e.g. "`{PLACEHOLDER_0}` enum") hashed to the same key and one file's cached
translation got served to another. The fix stops new collisions; it does
NOT retroactively heal ~200K files' worth of historical TM entries written
before it landed. This scanner finds the historical damage directly from
content, the same ground-truth approach used for the LLM-refusal scan.

Detection strategy: reference.aspose.org's API reference pages follow a
strict template -- `description`/`summary` contain a backtick-quoted
identifier that MUST match the file's own `title`/`linkTitle` (verified
structurally: en/pdf/java/Algorithm.md has title: Algorithm and
description: "`Algorithm` enum"). If the translated file's description names
a *different* backtick-quoted identifier than its own title, the TM served
a collided entry from an unrelated file.
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
# SITES intentionally excludes blog.aspose.org: this detector's logic
# (backtick-quoted identifier matching the file's own title/linkTitle) only
# applies to reference/docs/kb/products.aspose.org's API-reference-style
# template pages -- blog posts have no such template, so this is a real
# content-type scoping decision, not the file-suffix-layout coverage gap
# fixed elsewhere in the durable-fix consolidation. Discovery itself
# (iter_pairs below) is registry-driven so this remains correct if ever
# pointed at a differently-laid-out site.
SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org", "products.aspose.org"]

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
BACKTICK_ID_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")


def get_frontmatter(content: str) -> str:
    m = FM_RE.match(content)
    return m.group(1) if m else ""


def fm_field(fm: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.M)
    if not m:
        return None
    val = m.group(1).strip()
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        val = val[1:-1]
    return val


def check_file(en_content: str, tr_content: str) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    en_fm = get_frontmatter(en_content)
    tr_fm = get_frontmatter(tr_content)

    en_title = (fm_field(en_fm, "title") or fm_field(en_fm, "linkTitle") or "").strip()
    if not en_title or not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", en_title):
        return findings  # not a simple single-identifier API page; skip

    # Confirm EN source itself follows the expected template (description
    # names the same identifier as title) -- otherwise this file isn't the
    # pattern this detector targets, skip to avoid false positives.
    en_desc = fm_field(en_fm, "description") or ""
    en_ids = set(BACKTICK_ID_RE.findall(en_desc))
    if en_title not in en_ids:
        return findings

    for field in ("description", "summary"):
        tr_val = fm_field(tr_fm, field)
        if not tr_val:
            continue
        tr_ids = set(BACKTICK_ID_RE.findall(tr_val))
        if not tr_ids:
            continue
        if en_title not in tr_ids:
            # translated field names a class identifier, but not this file's own
            other = sorted(tr_ids)[0]
            findings.append(("tm_collision", f"field={field} expected=`{en_title}` found=`{other}`"))

    return findings


def iter_pairs(site: str):
    """Yield (locale, rel, en_path, tr_path) for existing translation pairs.
    Registry-driven via content_discovery."""
    try:
        profile = _CONFIG.get_site_profile(site)
    except Exception:
        return
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    if not content_root.exists():
        return
    source_root = resolve_source_root(profile, content_root)
    for en_path, locale, tr_path in iter_locale_pairs(profile, content_root):
        if not tr_path.exists():
            continue
        rel = en_path.relative_to(source_root)
        yield locale, str(rel), en_path, tr_path


def scan(output_path: str | None, sites: list[str] | None):
    results = defaultdict(lambda: defaultdict(int))
    examples = defaultdict(list)
    total_pairs = 0
    template_matches = 0

    out_fh = open(output_path, "w", encoding="utf-8") if output_path else None
    print(f"Starting TM-collision audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        site_pairs = 0
        site_findings = 0
        en_cache: dict[Path, str] = {}

        for locale, rel, en_path, tr_path in iter_pairs(site):
            site_pairs += 1
            total_pairs += 1
            if site_pairs % 10000 == 0:
                print(f"  {site}: {site_pairs:,} pairs scanned, {site_findings} findings so far", flush=True)
            try:
                if en_path not in en_cache:
                    en_cache[en_path] = en_path.read_text(encoding="utf-8", errors="replace")
                en_content = en_cache[en_path]
                tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            findings = check_file(en_content, tr_content)
            if findings:
                template_matches += 1
            for issue, detail in findings:
                results[site][issue] += 1
                site_findings += 1
                entry = {
                    "site": site, "locale": locale, "rel": rel,
                    "en_path": str(en_path), "tr_path": str(tr_path),
                    "issue": issue, "detail": detail,
                }
                if out_fh:
                    out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if len(examples[issue]) < 20:
                    examples[issue].append(entry)

        print(f"{site}: {site_pairs:,} pairs scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_pairs:,} total pairs scanned) ===")
    for site, issues in results.items():
        for issue, count in issues.items():
            print(f"  {site} :: {issue} = {count}")

    print("\n=== SAMPLE FINDINGS (up to 20) ===")
    for issue, entries in examples.items():
        print(f"\n--- {issue} ({len(entries)} shown) ---")
        for e in entries:
            print(f"  [{e['site']}/{e['locale']}] {e['rel']} :: {e['detail']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_tm_collision.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
