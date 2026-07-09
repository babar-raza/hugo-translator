"""
backfill_frontmatter_ids.py — Restore English title + linkTitle across translated files.

Fixes 18,859 corrupted title fields and 11,503 corrupted linkTitle fields in
reference.aspose.org translations, without touching the file body.

Algorithm:
  1. Walk all non-en locale dirs under {content_root}/reference.aspose.org/
  2. For each .md file, read first 25 lines (frontmatter region)
  3. Extract title: and linkTitle: values via regex (no YAML round-trip)
  4. Read English source's title/linkTitle the same way
  5. If either field differs from English → do in-place string replacement in frontmatter
  6. Write back full file with patched frontmatter, body bytes untouched

Usage:
  python scripts/quality/backfill_frontmatter_ids.py --dry-run   # default
  python scripts/quality/backfill_frontmatter_ids.py --apply
  python scripts/quality/backfill_frontmatter_ids.py --apply --locales ar,bg,ru
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SITE = "reference.aspose.org"
EN_LOCALE = "en"
FRONTMATTER_LINES = 25  # Read only first 25 lines for comparison
FRONTMATTER_END_RE = re.compile(r"^---\s*$")

# Match: title: SomeValue  OR  title: "Some Value"  OR  title: 'Some Value'
_FM_RE = re.compile(
    r'^(title|linkTitle):\s*(?:["\']?)(.+?)(?:["\']?)\s*$',
    re.MULTILINE,
)
# Stricter: match the exact line to replace (preserves quoting style)
_TITLE_LINE_RE = re.compile(r"^(title:\s*)(.*?)(\s*)$", re.MULTILINE)
_LINKTITLE_LINE_RE = re.compile(r"^(linkTitle:\s*)(.*?)(\s*)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_content_root() -> Path:
    """Return path to aspose.org/content, checking env vars then defaults."""
    env = os.environ.get("ASPOSE_ORG_CONTENT")
    if env:
        p = Path(env)
        if p.exists():
            return p
    defaults = [
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
    ]
    for p in defaults:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate aspose.org content root. Set ASPOSE_ORG_CONTENT env var."
    )


def _extract_fm_values(text: str) -> dict[str, str]:
    """Extract title and linkTitle from raw frontmatter text (first 25 lines)."""
    values: dict[str, str] = {}
    in_fm = False
    fm_end_count = 0
    lines = text.splitlines()[:FRONTMATTER_LINES]
    for line in lines:
        if FRONTMATTER_END_RE.match(line):
            fm_end_count += 1
            if fm_end_count == 1:
                in_fm = True
                continue
            else:
                break  # second --- means end of frontmatter
        if in_fm:
            m = re.match(r'^(title|linkTitle):\s*(.*?)\s*$', line)
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip('"').strip("'")
                values[key] = val
    return values


def _read_fm_region(path: Path) -> tuple[str, str]:
    """Read full file, return (raw_frontmatter_text, full_content)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    return content[:2000], content  # fm always within first 2KB


def _replace_fm_field(content: str, field: str, old_val: str, new_val: str) -> str:
    """Replace field value in frontmatter portion only (first occurrence)."""
    # Match: field: <anything>  (with or without quotes)
    pattern = re.compile(
        r'^(' + re.escape(field) + r':\s*)([^\n]*)',
        re.MULTILINE,
    )

    def _replacer(m: re.Match) -> str:
        prefix = m.group(1)  # e.g., "title: "
        current = m.group(2).strip().strip('"').strip("'")
        if current == old_val:
            # Preserve quoting style of new_val (none — API identifiers are bare)
            return prefix + new_val
        return m.group(0)  # unchanged

    # Only replace in frontmatter region (within first occurrence of --- ... ---)
    fm_end = content.find('\n---', 4)  # skip opening ---
    if fm_end == -1:
        return content
    fm_region = content[:fm_end]
    rest = content[fm_end:]
    new_fm = pattern.sub(_replacer, fm_region, count=1)
    return new_fm + rest


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def process_file(
    tr_path: Path,
    en_path: Path,
    apply: bool,
    stats: dict,
    locale: str,
) -> None:
    """Compare title/linkTitle between translated and English; patch if different."""
    if not en_path.exists():
        stats["en_missing"] += 1
        return

    # Read only first 25 lines for comparison (fast)
    try:
        tr_head = tr_path.read_text(encoding="utf-8", errors="replace")
        en_head = en_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stats["read_errors"] += 1
        return

    tr_fm = _extract_fm_values(tr_head)
    en_fm = _extract_fm_values(en_head)

    patches: dict[str, tuple[str, str]] = {}  # field -> (old, new)

    for field in ("title", "linkTitle"):
        en_val = en_fm.get(field, "")
        tr_val = tr_fm.get(field, "")
        if not en_val:
            continue  # no English value to restore
        if en_val and tr_val and tr_val != en_val:
            patches[field] = (tr_val, en_val)
            stats[f"{field}_mismatches"] += 1
            stats[f"locale_{locale}_{field}"] += 1

    if not patches:
        stats["files_ok"] += 1
        return

    stats["files_to_patch"] += 1

    if apply:
        content = tr_head  # already read full file
        for field, (old_val, new_val) in patches.items():
            content = _replace_fm_field(content, field, old_val, new_val)
        try:
            tr_path.write_text(content, encoding="utf-8")
            stats["files_patched"] += 1
        except OSError as e:
            print(f"  ERROR writing {tr_path}: {e}", file=sys.stderr)
            stats["write_errors"] += 1


def run(
    content_root: Path,
    only_locales: list[str] | None,
    apply: bool,
    verbose: bool,
) -> dict:
    site_root = content_root / SITE
    if not site_root.exists():
        raise FileNotFoundError(f"Site root not found: {site_root}")

    en_root = site_root / EN_LOCALE
    stats: dict = defaultdict(int)
    stats["files_scanned"] = 0

    # Discover locale directories
    locales = sorted(
        d.name
        for d in site_root.iterdir()
        if d.is_dir() and d.name != EN_LOCALE and (not only_locales or d.name in only_locales)
    )

    print(f"Content root: {site_root}")
    print(f"Locales: {locales}")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print()

    for locale in locales:
        locale_root = site_root / locale
        locale_files = list(locale_root.rglob("*.md"))
        print(f"  {locale}: {len(locale_files)} files", end="", flush=True)

        for tr_path in locale_files:
            stats["files_scanned"] += 1
            # Resolve English source: replace locale segment with 'en'
            rel = tr_path.relative_to(locale_root)
            en_path = en_root / rel
            process_file(tr_path, en_path, apply, stats, locale)

        locale_title = stats.get(f"locale_{locale}_title", 0)
        locale_link = stats.get(f"locale_{locale}_linkTitle", 0)
        print(f"  →  title_mismatch={locale_title}  linkTitle_mismatch={locale_link}")

    return dict(stats)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill English title/linkTitle into translated files")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Report mismatches only (default)")
    parser.add_argument("--apply", action="store_true", help="Apply patches in place")
    parser.add_argument("--content-root", type=Path, help="Path to aspose.org/content directory")
    parser.add_argument("--locales", type=str, help="Comma-separated locales to restrict (default: all)")
    parser.add_argument("--verbose", action="store_true", help="Print per-file details")
    args = parser.parse_args()

    apply = args.apply  # --apply overrides default dry-run

    content_root = args.content_root or _resolve_content_root()
    only_locales = [l.strip() for l in args.locales.split(",")] if args.locales else None

    stats = run(content_root, only_locales, apply=apply, verbose=args.verbose)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files scanned:      {stats.get('files_scanned', 0):>8,}")
    print(f"Files OK (no diff): {stats.get('files_ok', 0):>8,}")
    print(f"Files to patch:     {stats.get('files_to_patch', 0):>8,}")
    print(f"  title mismatches: {stats.get('title_mismatches', 0):>8,}")
    print(f"  linkTitle mismatches: {stats.get('linkTitle_mismatches', 0):>8,}")
    if apply:
        print(f"Files patched:      {stats.get('files_patched', 0):>8,}")
        print(f"Write errors:       {stats.get('write_errors', 0):>8,}")
    print(f"EN source missing:  {stats.get('en_missing', 0):>8,}")
    print(f"Read errors:        {stats.get('read_errors', 0):>8,}")
    print()
    if not apply:
        print("DRY-RUN complete. Run with --apply to patch files.")
    else:
        print("APPLY complete.")


if __name__ == "__main__":
    main()
