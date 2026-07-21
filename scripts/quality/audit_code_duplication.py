"""Full-corpus scan for the products.aspose.org single.block code-duplication
bug (found 2026-07-19 via a 9-way parallel manual audit of the 2026-07-03
professionalize_llm campaign): a `single.block[].content` YAML field's fenced
code sample gets duplicated in place, with a stray re-opened (and often never
re-closed) code fence, corrupting the block. Confirmed independently across
30+ locales, always in the exact same 3 EN source files (pdf/java, slides/cpp,
slides/java) and never in their clean siblings (pdf/net, slides/net,
slides/python) -- strongly deterministic and file-specific, not random
per-locale MT noise.

Also confirmed: corrupted files' `single.block[].content` fields are
serialized as a double-quoted YAML scalar (backslash line-continuations,
literal \\n escapes) rather than the clean `content: |` block-literal style
used by unaffected files -- a real YAML parser (not hand-rolled line
scanning) is required to read both styles correctly.

Detection: code is never translated, so the EN source's exact code-fence
body text must appear in the translated block too -- but exactly once. If it
appears 2+ times, the block was duplicated.
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

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content")
SITES = ["products.aspose.org"]

FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
CODE_FENCE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9]*\n(.*?)(?:```|\Z)", re.S)


def get_single_block_contents(content: str) -> list[str]:
    m = FM_RE.match(content)
    if not m:
        return []
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return []
    if not isinstance(fm, dict):
        return []
    single = fm.get("single")
    if not isinstance(single, dict):
        return []
    blocks = single.get("block")
    if not isinstance(blocks, list):
        return []
    return [b.get("content", "") for b in blocks if isinstance(b, dict)]


def check_file(en_content: str, tr_content: str) -> list[tuple[str, str]]:
    """Code is never translated, so the EN source's exact code-fence body
    text must appear in the translated block too -- but exactly once. If it
    appears 2+ times, the block was duplicated."""
    findings = []
    en_blocks = get_single_block_contents(en_content)
    tr_blocks = get_single_block_contents(tr_content)
    for i, en_block in enumerate(en_blocks):
        if i >= len(tr_blocks):
            continue
        tr_block = tr_blocks[i]
        for m in CODE_FENCE_BLOCK_RE.finditer(en_block):
            code_body = m.group(1).strip()
            if len(code_body) < 30:
                continue  # too short to be a reliable duplication signal
            occurrences = tr_block.count(code_body)
            if occurrences >= 2:
                findings.append(("code_block_duplicated", f"single.block[{i}]: code snippet appears {occurrences}x"))
                break  # one finding per block is enough
    return findings


def iter_pairs(site: str):
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


def scan(output_path: str | None, sites: list[str] | None):
    results = defaultdict(int)
    examples = []
    total_pairs = 0

    out_fh = open(output_path, "w", encoding="utf-8") if output_path else None
    print(f"Starting code-duplication audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        site_pairs = 0
        site_findings = 0
        en_cache: dict[Path, str] = {}

        for locale, rel, en_path, tr_path in iter_pairs(site):
            site_pairs += 1
            total_pairs += 1
            try:
                if en_path not in en_cache:
                    en_cache[en_path] = en_path.read_text(encoding="utf-8", errors="replace")
                en_content = en_cache[en_path]
                tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            findings = check_file(en_content, tr_content)
            for issue, detail in findings:
                results[rel] += 1
                site_findings += 1
                entry = {"site": site, "locale": locale, "rel": rel,
                          "en_path": str(en_path), "tr_path": str(tr_path),
                          "issue": issue, "detail": detail}
                if out_fh:
                    out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if len(examples) < 20:
                    examples.append(entry)

        print(f"{site}: {site_pairs:,} pairs scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_pairs:,} pairs scanned) ===")
    for rel, count in sorted(results.items(), key=lambda x: -x[1]):
        print(f"  {rel}: {count}")

    print("\n=== SAMPLE FINDINGS ===")
    for e in examples:
        print(f"  [{e['site']}/{e['locale']}] {e['rel']} :: {e['detail']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_code_duplication.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
