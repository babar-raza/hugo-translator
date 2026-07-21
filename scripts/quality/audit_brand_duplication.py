"""Full-corpus scan for the brand/product-name duplication pattern (Finding 4
of the 2026-07-19 16-agent quality audit's manual-reading pass): a translated
title/head_title/linkTitle/FAQ-question field mangles a
"Aspose.<Product> FOSS [for <Lang>]" template into
"Aspose.<Product> FOSS - <translated descriptor> FOSS [for|<translated-for>] <Lang>"
-- i.e. the acronym "FOSS" (never transliterated; stays literally "FOSS" in
every locale observed) appears TWICE in the translated field, immediately
preceded by a literal "Aspose.<X> FOSS -" prefix, where the EN source field
contains "FOSS" only once (or fewer times than the translation).

Verified against real files before writing this detector (2026-07-19):
  EN  docs.aspose.org/en/note/python/_index.md            title: "Aspose.Note FOSS for Python"
  AR  docs.aspose.org/ar/note/python/_index.md             title: "Aspose.Note FOSS - ملاحظة FOSS لـ Python"
  EN  docs.aspose.org/en/email/python/_index.md            title: "Aspose.Email FOSS for Python"
  AR  docs.aspose.org/ar/email/python/_index.md            title: "Aspose.Email FOSS - البريد الإلكتروني FOSS for Python"
  EN  products.aspose.org/en/words/python/_index.md        title: "Aspose.Words FOSS for Python"
  JA  products.aspose.org/ja/words/python/_index.md        title: "Aspose.Words FOSS - Aspose.Words Python 用 FOSS"
  EN  products.aspose.org/en/barcode/_index.md              title: "Aspose.BarCode FOSS"
  NO  products.aspose.org/no/barcode/_index.md               title: "Aspose.BarCode FOSS - Barkode FOSS"
  EN  products.aspose.org/en/note/python/_index.md  faq.list[0].question: "What is Aspose.Note FOSS for Python?"
  JA  products.aspose.org/ja/note/python/_index.md  faq.list[0].question: "Aspose.Note FOSS - Aspose.Note の Python 用のFOSSとは何ですか？"

A corpus-wide title/head_title/linktitle scan (all 5 sites, both schemes)
found ZERO instances on reference.aspose.org or blog.aspose.org -- the
pattern is confined to the "layout: plugin" family pages on
products.aspose.org and the dir-scheme _index.md pages on docs.aspose.org /
kb.aspose.org that carry a "Aspose.<Product> FOSS [for <Lang>]" title
template. Not restricted to any fixed locale list (confirmed present well
beyond the 9 locales the manual audit sampled, e.g. also "no").

Two site directory schemes handled (see scripts/quality/audit_llm_artifacts.py
for the reference iter_pairs_* implementations this reuses the shape of):
  - reference/docs/kb/products.aspose.org: <site>/en/<rel> vs <site>/<locale>/<rel>
  - blog.aspose.org: <site>/<rel>/index.md (EN) vs <site>/<rel>/index.<locale>.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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

# Structural duplication signature: "Aspose.<X> FOSS" then a dash, then (at
# least) one more "FOSS" later in the same field. FOSS is an acronym that is
# never transliterated across any observed locale, so this is a highly
# specific low-false-positive signal -- ordinary long sentences that merely
# mention "Aspose" or "FOSS" once each never match this shape.
FOSS_DUP_RE = re.compile(r"Aspose\.\S+\s*FOSS\s*[-–—]\s*.+FOSS")

MAX_FIELD_LEN = 300  # title-like fields only; guards against accidental body-text matches

# Top-level (column-0) scalar frontmatter fields to check, plus the two
# spelling variants seen for the link-title field across sites (docs.aspose.org
# / products.aspose.org use "linktitle", kb.aspose.org uses "linkTitle").
TOP_LEVEL_FIELDS = [
    ("title", ["title"]),
    ("head_title", ["head_title"]),
    ("subtitle", ["subtitle"]),
    ("linktitle", ["linktitle", "linkTitle"]),
]

FAQ_QUESTION_RE = re.compile(r"^\s*-\s*question:\s*(.+)$", re.M)


def get_frontmatter(content: str) -> str:
    m = FM_RE.match(content)
    return m.group(1) if m else ""


def fm_field(fm: str, keys: list[str]) -> str | None:
    for key in keys:
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.M)
        if m:
            val = m.group(1).strip()
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            return val
    return None


def fm_faq_questions(fm: str) -> list[str]:
    out = []
    for m in FAQ_QUESTION_RE.finditer(fm):
        val = m.group(1).strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        out.append(val)
    return out


def _is_duplicated(en_val: str | None, tr_val: str | None) -> bool:
    if not tr_val or len(tr_val) > MAX_FIELD_LEN:
        return False
    if not FOSS_DUP_RE.search(tr_val):
        return False
    en_foss_count = (en_val or "").count("FOSS")
    tr_foss_count = tr_val.count("FOSS")
    # require the translation to have strictly MORE "FOSS" occurrences than
    # the EN source -- this is what separates genuine duplication from a
    # field that legitimately says "FOSS" twice in both languages.
    return tr_foss_count > en_foss_count


def check_file(en_content: str, tr_content: str) -> list[tuple[str, str]]:
    """Return list of (issue_type, detail) findings for one EN/TR pair."""
    findings: list[tuple[str, str]] = []
    en_fm = get_frontmatter(en_content)
    tr_fm = get_frontmatter(tr_content)

    for field_name, keys in TOP_LEVEL_FIELDS:
        en_val = fm_field(en_fm, keys)
        tr_val = fm_field(tr_fm, keys)
        if _is_duplicated(en_val, tr_val):
            findings.append((f"brand_duplication_{field_name}", f"en={en_val[:100]!r} tr={tr_val[:150]!r}"))

    en_questions = fm_faq_questions(en_fm)
    tr_questions = fm_faq_questions(tr_fm)
    for i, tr_q in enumerate(tr_questions):
        en_q = en_questions[i] if i < len(en_questions) else None
        if _is_duplicated(en_q, tr_q):
            findings.append(("brand_duplication_faq_question", f"en={(en_q or '')[:100]!r} tr={tr_q[:150]!r}"))

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
    print(f"Starting brand-duplication audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

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

            file_findings = check_file(en_content, tr_content)
            if not file_findings:
                continue

            issues = []
            for issue, detail in file_findings:
                results[site][issue] += 1
                site_findings += 1
                issues.append({"issue": issue, "detail": detail})
                if len(examples[issue]) < 20:
                    examples[issue].append({
                        "site": site, "locale": locale, "rel": rel,
                        "en_path": str(en_path), "tr_path": str(tr_path), "detail": detail,
                    })

            entry = {
                "site": site,
                "locale": locale,
                "rel": rel,
                "issues": issues,
            }
            if out_fh:
                out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"{site}: {site_pairs:,} pairs scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_pairs:,} total pairs scanned across {len(sites if sites is not None else SITES)} sites) ===")
    total_findings = 0
    locale_counts: dict[str, int] = defaultdict(int)
    for site, issues in results.items():
        for issue, count in issues.items():
            print(f"  {site} :: {issue} = {count}")
            total_findings += count
    print(f"\nTotal findings: {total_findings}")

    print("\n=== SAMPLE FINDINGS (up to 20 per issue type) ===")
    for issue, entries in examples.items():
        print(f"\n--- {issue} ({len(entries)} shown) ---")
        for e in entries:
            print(f"  [{e['site']}/{e['locale']}] {e['rel']} :: {e['detail']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_brand_duplication.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
