"""
delete_for_retranslate.py — Delete corrupted locale files so running shards retranslate them.

Scans all 3 aspose.org sites for GPU-required quality issues and deletes the corrupted
locale files. Running shards detect the missing files and retranslate them fresh through
the hardened write gates. The Translation Memory (L2) is automatically updated by the
translation engine during retranslation.

Issue detectors (false-positive guarded):
  - shortcode_leak         : {{< or {{%  in tgt body but NOT in src body
  - description_hallucination : description length ratio > 3x or < 0.3x source
  - purity_issue           : > 10% ASCII lines in non-Latin-script locale body
  - newline_explosion      : translated lines > 2.5x source lines
  - body_identical_to_en   : translated body bytes == English source body bytes
  - empty_body             : translated body < 20 chars, English body > 50 chars
  - artifact_corruption    : known model artifact patterns in body
  - eu_hallucination       : GDPR/cookie text in body but NOT in source
  - table_row_corruption   : table row count ratio < 0.5 or > 2.0 vs source

Usage:
  python scripts/quality/delete_for_retranslate.py --dry-run            # default
  python scripts/quality/delete_for_retranslate.py --apply
  python scripts/quality/delete_for_retranslate.py --apply --sites all
  python scripts/quality/delete_for_retranslate.py --apply --sites docs.aspose.org
  python scripts/quality/delete_for_retranslate.py --apply --issue-type shortcode_leak
  python scripts/quality/delete_for_retranslate.py --apply --locales ar,ru
  python scripts/quality/delete_for_retranslate.py --apply --max-files 1000
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure sibling modules (e.g. frontmatter_utils) import correctly regardless
# of invocation mode (direct script run vs. pytest package import).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(_REPO_ROOT / "src"), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.locale_policy import (  # noqa: E402
    LocalePolicyViolation,
    filter_to_allowed_locales,
    validate_requested_locales,
)

_config_service: ConfigService | None = None


def _get_site_profile(site_id: str):
    """Fetch the live SiteProfile for site_id (None if not loadable)."""
    global _config_service
    if _config_service is None:
        _config_service = ConfigService(str(_REPO_ROOT / "config"))
    try:
        return _config_service.get_site_profile(site_id)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"

# Non-Latin-script locales: purity check only fires for these
NON_LATIN_LOCALES = frozenset({
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh",
})

# EU/GDPR hallucination patterns
_EU_PATTERNS = [
    re.compile(r"(?:cookie|GDPR|General Data Protection|privacy policy|data protection)", re.I),
    re.compile(r"(?:European Union|EU regulation|DSGVO|Datenschutz)", re.I),
]

# Known model artifact patterns
_ARTIFACT_PATTERNS = [
    re.compile(r"\?\?\?\?+"),                    # repeated question marks
    re.compile(r"\{\\?pos\s*\(\d+,\s*\d+\)\}"),  # SSA subtitle position tags
    re.compile(r"\[Pr[e\xe9]c[e\xe9]dent\]"),    # French "Previous" leaked artifact
    re.compile(r"\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u0439"),  # Cyrillic "Previous"
]

# Shortcode pattern (only fires when present in tgt but NOT in src)
_SHORTCODE_RE = re.compile(r"\{\{[<%]")


# ---------------------------------------------------------------------------
# Content root resolution
# ---------------------------------------------------------------------------


def _resolve_content_root() -> Path:
    env = os.environ.get("ASPOSE_ORG_CONTENT")
    if env:
        p = Path(env)
        if p.exists():
            return p
    defaults = [
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
    ]
    for p in defaults:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate aspose.org content root. Set ASPOSE_ORG_CONTENT env var."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_body(content: str) -> str:
    """Strip frontmatter (--- ... ---) and return the body."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    return content[end + 4:]


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks."""
    return re.sub(r"```[\s\S]*?```", "", text)


def _count_table_rows(text: str) -> int:
    """Count lines that start AND end with | outside code blocks."""
    clean = _strip_code_blocks(text)
    return sum(
        1
        for line in clean.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    )


# ---------------------------------------------------------------------------
# Issue detectors
# ---------------------------------------------------------------------------


def _detect_shortcode_leak(en_content: str, tr_content: str) -> bool:
    """Shortcode patterns in tgt body that are NOT in src body."""
    src_body = _get_body(en_content)
    tgt_body = _get_body(tr_content)
    src_codes = set(_SHORTCODE_RE.findall(src_body))
    tgt_codes = set(_SHORTCODE_RE.findall(tgt_body))
    # Only flag if tgt has shortcodes that didn't come from src
    return bool(tgt_codes - src_codes)


def _detect_description_hallucination(en_content: str, tr_content: str) -> bool:
    """Description field length ratio > 3x or < 0.3x source.

    Parses frontmatter via HugoParser rather than a first-line regex, so
    multi-line folded/literal scalars are compared by their full value
    instead of being truncated to the first physical line (TC-HT-001).
    """
    from frontmatter_utils import get_frontmatter_field

    src = get_frontmatter_field(en_content, "description")
    tgt = get_frontmatter_field(tr_content, "description")
    if not src or not tgt or len(src) < 20:
        return False
    ratio = len(tgt) / len(src)
    return ratio > 3.0 or ratio < 0.3


def _detect_purity_issue(en_content: str, tr_content: str, locale: str) -> bool:
    """More than 30% of non-trivial prose lines are pure ASCII in a non-Latin locale.

    Prose lines only: headings (#), table rows (|), shortcodes ({{) and blank
    lines are excluded. Minimum source body 100 chars to skip stubs.
    30% threshold avoids false positives on API reference files that legitimately
    have many English code identifiers in surrounding translated text.
    """
    if locale not in NON_LATIN_LOCALES:
        return False
    src_body = _get_body(en_content)
    if len(src_body.strip()) < 100:
        return False
    body = _get_body(tr_content)
    clean = _strip_code_blocks(body)
    prose_lines = []
    for raw in clean.splitlines():
        s = raw.strip()
        if len(s) < 30:
            continue
        if s.startswith("#") or s.startswith("|") or s.startswith("{{") or s.startswith(">"):
            continue
        prose_lines.append(s)
    if len(prose_lines) < 5:
        return False  # too few prose lines to judge
    ascii_count = sum(
        1 for l in prose_lines
        if re.fullmatch(r"[A-Za-z0-9\s.,;:!?\-'\"()\[\]{}@#$%^&*+=/<>|~`_\\]+", l)
    )
    return (ascii_count / len(prose_lines)) > 0.30


def _detect_newline_explosion(en_content: str, tr_content: str) -> bool:
    """Translated lines > 2.5x source lines."""
    src_lines = _get_body(en_content).count("\n")
    tgt_lines = _get_body(tr_content).count("\n")
    if src_lines < 10:
        return False
    return tgt_lines > src_lines * 2.5


def _detect_body_identical_to_en(en_content: str, tr_content: str) -> bool:
    """Translated body bytes identical to English source body."""
    src_body = _get_body(en_content).strip()
    tgt_body = _get_body(tr_content).strip()
    if len(src_body) < 50:
        return False
    return src_body == tgt_body


def _detect_empty_body(en_content: str, tr_content: str) -> bool:
    """Translated body < 20 chars while English body > 50 chars."""
    src_body = _get_body(en_content).strip()
    tgt_body = _get_body(tr_content).strip()
    return len(tgt_body) < 20 and len(src_body) > 50


def _detect_artifact_corruption(tr_content: str) -> bool:
    """Known model artifact patterns present in body."""
    body = _get_body(tr_content)
    return any(p.search(body) for p in _ARTIFACT_PATTERNS)


def _detect_eu_hallucination(en_content: str, tr_content: str) -> bool:
    """GDPR/cookie text in tgt body not present in src body."""
    src_body = _get_body(en_content)
    tgt_body = _get_body(tr_content)
    return any(p.search(tgt_body) and not p.search(src_body) for p in _EU_PATTERNS)


def _detect_table_row_corruption(en_content: str, tr_content: str) -> bool:
    """Table row count ratio < 0.5 or > 2.0 vs source."""
    src_body = _get_body(en_content)
    tgt_body = _get_body(tr_content)
    src_rows = _count_table_rows(src_body)
    tgt_rows = _count_table_rows(tgt_body)
    if src_rows < 4:
        return False
    ratio = tgt_rows / max(src_rows, 1)
    return ratio < 0.5 or ratio > 2.0


ALL_DETECTORS: dict[str, callable] = {
    "shortcode_leak": _detect_shortcode_leak,
    "description_hallucination": _detect_description_hallucination,
    "purity_issue": _detect_purity_issue,
    "newline_explosion": _detect_newline_explosion,
    "body_identical_to_en": _detect_body_identical_to_en,
    "empty_body": _detect_empty_body,
    "artifact_corruption": _detect_artifact_corruption,
    "eu_hallucination": _detect_eu_hallucination,
    "table_row_corruption": _detect_table_row_corruption,
}

# Detectors that take (en_content, tr_content) only (no locale arg)
_TWO_ARG_DETECTORS = {
    "shortcode_leak", "description_hallucination", "newline_explosion",
    "body_identical_to_en", "empty_body", "eu_hallucination", "table_row_corruption",
}
# Detectors that take (en_content, tr_content, locale)
_THREE_ARG_DETECTORS = {"purity_issue"}
# Detectors that take (tr_content) only
_ONE_ARG_DETECTORS = {"artifact_corruption"}


def detect_issues(
    en_content: str,
    tr_content: str,
    locale: str,
    only_issues: set[str] | None,
) -> list[str]:
    """Run all (or filtered) detectors. Returns list of triggered issue names."""
    triggered = []
    detectors = only_issues if only_issues else set(ALL_DETECTORS.keys())
    for name in detectors:
        fn = ALL_DETECTORS.get(name)
        if fn is None:
            continue
        try:
            if name in _ONE_ARG_DETECTORS:
                result = fn(tr_content)
            elif name in _THREE_ARG_DETECTORS:
                result = fn(en_content, tr_content, locale)
            else:
                result = fn(en_content, tr_content)
            if result:
                triggered.append(name)
        except Exception:
            pass  # detector failure is non-fatal
    return triggered


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------


def process_file(
    tr_path: Path,
    en_path: Path,
    locale: str,
    apply: bool,
    only_issues: set[str] | None,
    stats: dict,
    verbose: bool,
) -> None:
    if not en_path.exists():
        stats["en_missing"] += 1
        return

    try:
        tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
        en_content = en_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stats["read_errors"] += 1
        return

    issues = detect_issues(en_content, tr_content, locale, only_issues)

    if not issues:
        stats["files_clean"] += 1
        return

    stats["files_flagged"] += 1
    for issue in issues:
        stats[f"issue_{issue}"] += 1

    if verbose:
        print(f"    [{', '.join(sorted(issues))}] {tr_path.name}")

    if apply:
        try:
            tr_path.unlink()
            stats["files_deleted"] += 1
            for issue in issues:
                stats[f"deleted_{issue}"] += 1
        except OSError as e:
            print(f"  ERROR deleting {tr_path}: {e}", file=sys.stderr)
            stats["delete_errors"] += 1


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run(
    content_root: Path,
    sites: list[str],
    only_locales: list[str] | None,
    apply: bool,
    only_issues: set[str] | None,
    max_files: int | None,
    verbose: bool,
) -> dict:
    stats: dict = defaultdict(int)

    print(f"Mode: {'APPLY (delete flagged files)' if apply else 'DRY-RUN'}")
    if only_issues:
        print(f"Issue filter: {', '.join(sorted(only_issues))}")
    print()

    if apply:
        print("WARNING: --apply will PERMANENTLY DELETE flagged locale files.")
        print("         Running shards will detect them as missing and retranslate.")
        print()

    files_processed = 0

    for site_id in sites:
        site_root = content_root / site_id
        if not site_root.exists():
            print(f"  SKIP {site_id}: not found at {site_root}")
            continue

        en_root = site_root / EN_LOCALE

        locales = sorted(
            d.name
            for d in site_root.iterdir()
            if d.is_dir() and d.name != EN_LOCALE
            and (not only_locales or d.name in only_locales)
        )
        if not only_locales:
            # Auto-discovery must never pick up a locale retired from this
            # site's active profile, even if its directory still exists on
            # disk (existing translated content is preserved, not deleted).
            locales = filter_to_allowed_locales(_get_site_profile(site_id), locales)

        print(f"Site: {site_id}  ({len(locales)} locales)")

        for locale in locales:
            locale_root = site_root / locale
            locale_files = list(locale_root.rglob("*.md"))

            print(f"  {locale}: {len(locale_files)} files", end="", flush=True)

            for tr_path in locale_files:
                if max_files and files_processed >= max_files:
                    break
                stats["files_scanned"] += 1
                files_processed += 1

                rel = tr_path.relative_to(locale_root)
                en_path = en_root / rel
                process_file(tr_path, en_path, locale, apply, only_issues, stats, verbose)

            flagged = stats["files_flagged"]
            deleted = stats["files_deleted"]
            print(f"  (flagged={flagged}, deleted={deleted})")

            if max_files and files_processed >= max_files:
                print(f"  Reached --max-files={max_files} limit.")
                break

        if max_files and files_processed >= max_files:
            break

        print()

    return dict(stats)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete corrupted locale files for shard retranslation"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Report flagged files only, do not delete (default)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Delete flagged files (shards will retranslate them)",
    )
    parser.add_argument(
        "--content-root", type=Path,
        help="Path to aspose.org/content directory",
    )
    parser.add_argument(
        "--sites", type=str, default="all",
        help="Comma-separated site names or 'all' (default: all)",
    )
    parser.add_argument(
        "--locales", type=str,
        help="Comma-separated locales to restrict (default: all)",
    )
    parser.add_argument(
        "--issue-type", type=str,
        help=(
            "Comma-separated issue types to restrict (default: all). "
            "Choices: " + ", ".join(sorted(ALL_DETECTORS))
        ),
    )
    parser.add_argument(
        "--max-files", type=int,
        help="Cap on total files to process (for testing)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print each flagged file name",
    )
    args = parser.parse_args()

    apply = args.apply
    content_root = args.content_root or _resolve_content_root()
    only_locales = [loc.strip() for loc in args.locales.split(",")] if args.locales else None
    only_issues: set[str] | None = None
    if args.issue_type:
        only_issues = {i.strip() for i in args.issue_type.split(",")}
        unknown = only_issues - set(ALL_DETECTORS)
        if unknown:
            print(f"ERROR: Unknown issue types: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"Valid choices: {', '.join(sorted(ALL_DETECTORS))}", file=sys.stderr)
            sys.exit(1)

    if args.sites.lower() == "all":
        sites = ALL_SITES
    else:
        sites = [s.strip() for s in args.sites.split(",")]

    if only_locales:
        # For strict_locale_allowlist sites, deleting content in a locale
        # outside target_langs is never permitted, even if explicitly
        # requested — must fail loudly, not silently no-op. No-op for
        # non-strict sites.
        for site_id in sites:
            try:
                validate_requested_locales(_get_site_profile(site_id), only_locales)
            except LocalePolicyViolation as e:
                print(f"ERROR: {e}", file=sys.stderr)
                sys.exit(1)

    stats = run(
        content_root=content_root,
        sites=sites,
        only_locales=only_locales,
        apply=apply,
        only_issues=only_issues,
        max_files=args.max_files,
        verbose=args.verbose,
    )

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files scanned:              {stats.get('files_scanned', 0):>8,}")
    print(f"Files clean:                {stats.get('files_clean', 0):>8,}")
    print(f"Files flagged:              {stats.get('files_flagged', 0):>8,}")
    print()

    issue_keys = [k for k in sorted(stats) if k.startswith("issue_")]
    if issue_keys:
        print("Issue counts (unique files):")
        for k in issue_keys:
            label = k.replace("issue_", "")
            print(f"  {label:35s} {stats[k]:>6,}")
        print()

    if apply:
        print(f"Files deleted:              {stats.get('files_deleted', 0):>8,}")
        del_keys = [k for k in sorted(stats) if k.startswith("deleted_")]
        for k in del_keys:
            print(f"  {k.replace('deleted_', ''):35s} {stats[k]:>6,}")
        print(f"Delete errors:              {stats.get('delete_errors', 0):>8,}")

    print(f"EN source missing:          {stats.get('en_missing', 0):>8,}")
    print(f"Read errors:                {stats.get('read_errors', 0):>8,}")
    print()

    if not apply:
        print("DRY-RUN complete. Run with --apply to delete flagged files.")
        print("  Shards will then retranslate deleted files through hardened gates.")
    else:
        deleted = stats.get("files_deleted", 0)
        print(f"APPLY complete. {deleted:,} files deleted and queued for shard retranslation.")


if __name__ == "__main__":
    main()
