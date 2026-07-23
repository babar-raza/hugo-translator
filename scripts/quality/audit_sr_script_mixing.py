"""Full sr-locale scan for Cyrillic/Latin script-mixing within a single
markdown bullet list (Finding 5 of the 2026-07-19 16-agent quality audit's
"group 2" sub-agent): some `- ` bullet items translated into Cyrillic
Serbian while adjacent bullets in the SAME list stay in Latin-script
Serbian or plain English, inconsistently.

Scans every sr file across all 5 sites (both directory schemes). For each
markdown body, groups consecutive `- `/`* ` bullet-list lines into blocks,
classifies each item's dominant script (cyrillic / latin / ambiguous) after
stripping inline code spans, link URLs, and a curated list of technical/
brand loanwords that legitimately stay Latin in Serbian text (Aspose.X,
.NET, C++, C#, API, PDF, JSON, etc. -- these must NOT cause a false
"mixed" classification), then flags any block containing both a cyrillic-
classified item and a latin-classified item.
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
# Durable-fix consolidation: registry-driven site list (was a hardcoded
# 5-site list) + registry-driven discovery (was a hand-rolled
# BLOG_SCHEME_SITES special case + duplicate iter_pairs_directory_scheme/
# iter_pairs_blog_scheme pair) via src/utils/content_discovery.py.
SITES = _CONFIG.list_sites(autonomous_only=True)

FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.+)$")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # keep link text, drop URL
CYR_RE = re.compile(r"[Ѐ-ӿ]")
LAT_RE = re.compile(r"[A-Za-z]")

# Technical/brand loanwords that legitimately stay in Latin script inside
# otherwise-Cyrillic Serbian text -- stripped before script classification
# so they don't cause false "mixed" or false "latin" classifications.
_LOANWORD_RE = re.compile(
    r"\bAspose(?:\.\w+)*\b"
    r"|\.NET\b|C\+\+|C#|\bSDK\b|\bAPI\b|\bPDF\b|\bJSON\b|\bXML\b|\bHTML\b|\bCSS\b"
    r"|\bURL\b|\bID\b|\bIDs\b|\bGUI\b|\bSQL\b|\bGitHub\b|\bMIT\b|\bREADME\b"
    r"|\bPython\b|\bJava\b|\bJavaScript\b|\bTypeScript\b|\bNode\.js\b"
    r"|\bWindows\b|\bLinux\b|\bmacOS\b|\bDocker\b|\bNuGet\b|\bpip\b|\bnpm\b"
    r"|\bUTF-8\b|\bUnicode\b|\bASCII\b|\bREST\b|\bHTTP[Ss]?\b"
    r"|\bDPI\b|\bRGB\b|\bCMYK\b|\bPNG\b|\bJPEG\b|\bJPG\b|\bSVG\b|\bTIFF\b|\bGIF\b"
    r"|\bDOCX?\b|\bXLSX?\b|\bPPTX?\b|\bCSV\b|\bZIP\b|\bTXT\b"
)

MIN_LATIN_LETTERS_FOR_LATIN = 8  # a real Latin sentence, not stray noise


def get_body(content: str) -> str:
    m = FM_RE.match(content)
    return content[m.end():] if m else content


def classify(item_text: str) -> str | None:
    """Return 'cyrillic', 'latin', or None (ambiguous/skip)."""
    t = CODE_SPAN_RE.sub(" ", item_text)
    t = LINK_RE.sub(r"\1", t)
    t = _LOANWORD_RE.sub(" ", t)
    cyr = len(CYR_RE.findall(t))
    lat = len(LAT_RE.findall(t))
    if cyr > 0 and lat == 0:
        return "cyrillic"
    if cyr > 0 and lat <= 2:
        # stray leftover Latin letters (e.g. a lone unit abbreviation) --
        # still treat as cyrillic-dominant
        return "cyrillic"
    if cyr == 0 and lat >= MIN_LATIN_LETTERS_FOR_LATIN:
        return "latin"
    return None


def find_mixed_blocks(body: str) -> list[dict]:
    """Return list of {items: [(text, script), ...]} for bullet blocks that
    mix cyrillic- and latin-classified items."""
    lines = body.splitlines()
    in_code = False
    blocks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []

    def flush():
        if len(current) >= 2:
            scripts = {s for _, s in current if s}
            if "cyrillic" in scripts and "latin" in scripts:
                blocks.append(list(current))
        current.clear()

    for line in lines:
        s = line.rstrip("\n")
        stripped = s.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            flush()
            continue
        if in_code:
            continue
        m = BULLET_RE.match(s)
        if m:
            item_text = m.group(2).strip()
            script = classify(item_text)
            current.append((item_text, script))
        else:
            if stripped == "":
                # blank line inside a list is common in markdown (loose
                # lists) -- don't break the block on blank lines alone
                continue
            flush()
    flush()

    return [{"items": b} for b in blocks]


def iter_locale_files(site: str, locale: str = "sr"):
    """Yield (rel, tr_path) for existing translated files in one locale.
    Registry-driven via content_discovery -- works identically for
    directory-scheme and file-suffix-scheme sites, no per-site branching."""
    try:
        profile = _CONFIG.get_site_profile(site)
    except Exception:
        return
    content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
    if not content_root.exists():
        return
    source_root = resolve_source_root(profile, content_root)
    for en_path, loc, tr_path in iter_locale_pairs(profile, content_root):
        if loc != locale or not tr_path.exists():
            continue
        yield str(en_path.relative_to(source_root)), tr_path


def scan(output_path: str | None, sites: list[str] | None, min_body_len: int):
    results = defaultdict(int)
    examples = []
    total_files = 0
    total_findings = 0

    out_fh = open(output_path, "w", encoding="utf-8") if output_path else None
    print(f"Starting sr script-mixing audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in (sites if sites is not None else SITES):
        iterator = iter_locale_files(site)
        site_files = 0
        site_findings = 0

        for rel, tr_path in iterator:
            site_files += 1
            total_files += 1
            try:
                content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            body = get_body(content)
            if len(body) < min_body_len:
                continue

            blocks = find_mixed_blocks(body)
            if not blocks:
                continue

            results[site] += len(blocks)
            site_findings += len(blocks)
            total_findings += len(blocks)
            entry = {
                "site": site, "locale": "sr", "rel": rel, "tr_path": str(tr_path),
                "issue": "sr_script_mixing_bullet_list",
                "blocks": [
                    [{"text": t[:160], "script": sc} for t, sc in blk["items"]]
                    for blk in blocks
                ],
            }
            if out_fh:
                out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if len(examples) < 60:
                examples.append(entry)

        print(f"{site}: {site_files:,} sr files scanned, {site_findings} findings", flush=True)

    if out_fh:
        out_fh.close()

    print(f"\n=== SUMMARY ({total_files:,} sr files scanned, {total_findings} mixed-script blocks) ===")
    for site, count in results.items():
        print(f"  {site}: {count}")

    print("\n=== SAMPLE FINDINGS ===")
    for e in examples:
        print(f"\n  [{e['site']}/sr] {e['rel']}")
        for blk in e["blocks"]:
            for item in blk:
                print(f"      ({item['script'] or '?'}) {item['text']}")

    return results, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=None)
    ap.add_argument("--output", default="data/audit/audit_sr_script_mixing.jsonl")
    ap.add_argument("--min-body-len", type=int, default=800,
                     help="skip very short files (favor developer-guide/feature-list pages)")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites, args.min_body_len)
