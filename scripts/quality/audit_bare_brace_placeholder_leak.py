"""Full-corpus scan for the bare-brace-wrapped-correct-value placeholder
leak fixed 2026-07-22 in PlaceholderManager.restore() (see
src/translation_engine/extractor/placeholder_manager.py).

Root cause: reference.aspose.org's frontmatter preserve_patterns have no
backtick-specific rule (backticks are only protected via the AST-level
`codespan` preserve_block, which doesn't apply to frontmatter strings) --
only the bare PascalCase pattern matches an identifier like "ColumnInfo"
without its surrounding backticks, so the placeholder token ends up sitting
directly between literal backtick and brace characters:
"`{PLACEHOLDER_0}` class...". When the MT model correctly guessed the
identifier but kept the literal `{`/`}` around it instead of the exact
"PLACEHOLDER_0" token, none of the (now fixed) restore() passes caught it,
shipping output like "`{ColumnInfo}` clase con 3 propiedades" instead of
"`ColumnInfo` clase con 3 propiedades".

All 1,109 files found by the first pass of this scan (2026-07-22) had
today's mtime -- this is damage from TODAY's own remediation campaigns
(retranslate_queue, tm_collision, cross_locale_dup, etc.), not historical.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
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
SITES = ["reference.aspose.org"]  # only site whose frontmatter preserve_patterns lack a backtick rule

FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.S)
BRACE_RE = re.compile(r"\{[A-Z][A-Za-z0-9]*\}")


def iter_locale_files(site: str):
    """Yield (locale, rel, en_path, tr_path) for existing translated files.
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
        if tr_path.exists():
            yield locale, en_path.relative_to(source_root), en_path, tr_path


def scan(output_path: str, sites: list[str]):
    results = []
    out_fh = open(output_path, "w", encoding="utf-8")
    print(f"Starting bare-brace placeholder leak audit at {datetime.now().strftime('%H:%M:%S')}", flush=True)

    for site in sites:
        site_findings = 0
        for locale, rel, en_path, tr_path in iter_locale_files(site):
            try:
                content = tr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            m = FM_RE.match(content)
            if not m or not BRACE_RE.search(m.group(1)):
                continue
            site_findings += 1
            entry = {
                "site": site, "locale": locale, "rel": str(rel),
                "en_path": str(en_path), "tr_path": str(tr_path),
                "issue": "bare_brace_placeholder_leak",
            }
            out_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            results.append(entry)
        print(f"{site}: {site_findings} findings", flush=True)

    out_fh.close()
    print(f"\n=== SUMMARY ({len(results)} findings) ===")
    by_locale: dict[str, int] = {}
    for e in results:
        by_locale[e["locale"]] = by_locale.get(e["locale"], 0) + 1
    for locale, count in sorted(by_locale.items(), key=lambda x: -x[1]):
        print(f"  {locale}: {count}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", nargs="+", default=SITES)
    ap.add_argument("--output", default="data/audit/audit_bare_brace_placeholder_leak.jsonl")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    scan(args.output, args.sites)
