"""Full-corpus scan for raw LLM refusal/meta-commentary text leaked into
production translations, plus a companion "brand token missing" check.

Discovered 2026-07-18: professionalize_llm (a real chat-completions API) is
routed via config/global.yaml's content_type_routing for short frontmatter
fields (title, description, etc. -- see content_type_routing.frontmatter_description
and the table_cell_text short-API-description rule) regardless of which
--model flag a run script passed for body content. Nothing validates that its
response is actually a translation rather than a refusal/clarifying-question/
meta-commentary reply (e.g. "Ich habe keine Ahnung.", "Please provide the
English text you want translated.", "Cože?"). Confirmed instances found in
products.aspose.org and blog.aspose.org during a manual sampling pass;
this script scans EVERY translated file (not a sample) across all 5 sites.

Two site directory schemes are both handled:
  - reference/docs/kb/products.aspose.org: <site>/en/<rel> vs <site>/<locale>/<rel>
  - blog.aspose.org: <site>/<rel>/index.md (EN) vs <site>/<rel>/index.<locale>.md

Detectors:
  1. refusal_keyword -- short frontmatter field or heading/link text contains a
     known refusal/meta-commentary phrase (curated multi-language list).
  2. leading_dash_short -- title/heading field is suspiciously short and starts
     with a bare "- " or similar dash prefix (matches 2 of 3 confirmed cases).
  3. brand_token_missing -- EN title contains "Aspose" (near-universal on this
     site) but the translated title contains no recognizable Aspose-brand
     token at all (case-insensitive substring). Catches refusals AND other
     severe defects (TM contamination, total mistranslation) in one check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.translation_engine.quality.refusal_patterns import (  # noqa: E402
    ASPOSE_TOKEN_RE as _ASPOSE_TOKEN_RE,
    LEADING_DASH_RE as _LEADING_DASH_RE,
    REFUSAL_RE as _REFUSAL_RE,
)

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content")
SITES = [
    "reference.aspose.org",
    "docs.aspose.org",
    "kb.aspose.org",
    "blog.aspose.org",
    "products.aspose.org",
]
BLOG_SCHEME_SITES = {"blog.aspose.org"}

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)

# Phrase list and compiled patterns now live in
# src/translation_engine/quality/refusal_patterns.py (single source of
# truth, TC-QG-001 HT-QUALITY-GATES-001) -- imported above as
# _REFUSAL_RE / _LEADING_DASH_RE / _ASPOSE_TOKEN_RE. Kept as the same names
# here so the rest of this script is unchanged.


def get_frontmatter(content: str) -> str:
    m = FM_RE.match(content)
    return m.group(1) if m else ""


def get_body(content: str) -> str:
    m = FM_RE.match(content)
    return content[m.end():] if m else content


def fm_field(fm: str, key: str) -> str | None:
    # handles quoted, unquoted, and single-quoted scalar values on one line
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.M)
    if not m:
        return None
    val = m.group(1).strip()
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        val = val[1:-1]
    return val


def check_file(en_content: str, tr_content: str) -> list[tuple[str, str]]:
    """Return list of (issue_type, detail) findings for one EN/TR pair."""
    findings: list[tuple[str, str]] = []
    en_fm = get_frontmatter(en_content)
    tr_fm = get_frontmatter(tr_content)
    tr_body = get_body(tr_content)

    en_title = fm_field(en_fm, "title") or ""
    tr_title = fm_field(tr_fm, "title") or ""

    # Detector 1: refusal keyword anywhere in the raw frontmatter block --
    # catches named top-level fields (title, description, ...) AND nested
    # YAML list/array fields (content.block bullets, faq.list entries,
    # overview.content), plus in the body.
    for m in _REFUSAL_RE.finditer(tr_fm):
        line_start = tr_fm.rfind("\n", 0, m.start()) + 1
        line_end = tr_fm.find("\n", m.end())
        line = tr_fm[line_start: line_end if line_end != -1 else None].strip()
        findings.append(("refusal_keyword_frontmatter", line[:160]))

    in_code = False
    for line in tr_body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s:
            continue
        if _REFUSAL_RE.search(s):
            findings.append(("refusal_keyword_body", s[:160]))

    # Detector 2: leading-dash short title
    if tr_title and len(tr_title) <= 60 and _LEADING_DASH_RE.match(tr_title):
        findings.append(("leading_dash_short_title", tr_title[:120]))

    # Detector 3: brand token missing (only when EN title clearly names the brand)
    if _ASPOSE_TOKEN_RE.search(en_title) and tr_title:
        if not _ASPOSE_TOKEN_RE.search(tr_title):
            findings.append(("brand_token_missing_title", f"en={en_title[:80]!r} tr={tr_title[:80]!r}"))

    return findings


def iter_pairs_directory_scheme(site: str):
    site_root = CONTENT_ROOT / site
    en_root = site_root / "en"
    if not en_root.exists():
        return
    locales = sorted(
        d.name for d in site_root.iterdir()
        if d.is_dir() and d.name != "en" and 2 <= len(d.name) <= 5 and d.name.replace("-", "").isalpha()
    )
    for en_path in sorted(en_root.rglob("*.md")):
        rel = en_path.relative_to(en_root)
        for locale in locales:
            tr_path = site_root / locale / rel
            if tr_path.exists():
                yield locale, str(rel), en_path, tr_path


def iter_pairs_blog_scheme(site: str):
    site_root = CONTENT_ROOT / site
    for en_path in sorted(site_root.rglob("index.md")):
        bundle_dir = en_path.parent
        rel = bundle_dir.relative_to(site_root)
        for tr_path in sorted(bundle_dir.glob("index.*.md")):
            locale = tr_path.stem.split(".", 1)[1]
            yield locale, str(rel), en_path, tr_path


def scan(output_path: str | None, sites: list[str] | None):
    results = defaultdict(lambda: defaultdict(int))
    examples = defaultdict(list)
    total_pairs = 0

    out_fh = open(output_path, "w", encoding="utf-8") if output_path else None
    print(f"Starting LLM-artifact audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        is_blog = site in BLOG_SCHEME_SITES
        pairs = iter_pairs_blog_scheme(site) if is_blog else iter_pairs_directory_scheme(site)
        site_pairs = 0
        site_findings = 0
        en_cache: dict[Path, str] = {}

        for locale, rel, en_path, tr_path in pairs:
            site_pairs += 1
            total_pairs += 1
            if site_pairs % 5000 == 0:
                print(f"  {site}: {site_pairs:,} pairs scanned, {site_findings} findings so far", flush=True)
            try:
                if en_path not in en_cache:
                    en_cache[en_path] = en_path.read_text(encoding="utf-8", errors="replace")
                en_content = en_cache[en_path]
                tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for issue, detail in check_file(en_content, tr_content):
                results[site][issue] += 1
                site_findings += 1
                entry = {
                    "site": site,
                    "locale": locale,
                    "rel": rel,
                    "en_path": str(en_path),
                    "tr_path": str(tr_path),
                    "issue": issue,
                    "detail": detail,
                }
                if out_fh:
                    out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if len(examples[issue]) < 15:
                    examples[issue].append(entry)

        print(f"{site}: {site_pairs:,} pairs scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_pairs:,} total pairs scanned across {len(sites if sites is not None else SITES)} sites) ===")
    for site, issues in results.items():
        for issue, count in issues.items():
            print(f"  {site} :: {issue} = {count}")

    print("\n=== SAMPLE FINDINGS (up to 15 per issue type) ===")
    for issue, entries in examples.items():
        print(f"\n--- {issue} ({len(entries)} shown) ---")
        for e in entries:
            print(f"  [{e['site']}/{e['locale']}] {e['rel']} :: {e['detail']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_llm_artifacts.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
