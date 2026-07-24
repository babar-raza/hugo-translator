"""heal_english_headings_dictionary.py — patch existing English headings
using the reviewed i18n template-string table (no LLM/MT calls).

Mission: heading-i18n-governance-20260723, taskcard TC-HT-I18N-007. See
C:\\Users\\prora\\.claude\\plans\\glittery-waddling-moth.md §7 for the
taskcard spec this implements.

For every already-translated file, live re-scans (NOT the stale audit
JSONL) for markdown heading lines whose text exactly matches an `approved`
entry in config/i18n/template_strings/_registry.yaml with a translation
for that locale, and rewrites just that heading's text — preserving `#`
depth and everything else in the file byte-identical. Writes go through
scripts/quality/safe_io.py's load()/save() choke point (gate-checked,
quarantined on failure) — the SAME artifact the live engine now consults
(TC-HT-I18N-004), so healing and live translation cannot drift apart.

Mandatory preflight (plan §6): before any --apply, diffs the candidate
file list against `git status --short` in the content repo and reports
any file that already has unrelated uncommitted changes, so those diffs
never get silently folded into this healer's commit.

Usage:
  python scripts/quality/heal_english_headings_dictionary.py --dry-run --sites all
  python scripts/quality/heal_english_headings_dictionary.py --apply --sites reference.aspose.org --locales ja --max-files 20
  python scripts/quality/heal_english_headings_dictionary.py --apply --sites all
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import safe_io  # noqa: E402

from src.translation_engine.terminology.classification import (  # noqa: E402
    TemplateStringRegistry,
)

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"
NON_LATIN_LOCALES = ["ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh"]

_HEADING_RE = re.compile(r"^(#{1,6})(\s+)(.+)$", re.MULTILINE)


def _resolve_content_root() -> Path:
    for var in ("ASPOSE_ORG_CONTENT_REPO", "ASPOSE_ORG_CONTENT"):
        env = os.environ.get(var)
        if env:
            p = Path(env)
            if p.exists():
                return p
    for p in [
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
    ]:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot find content root. Set ASPOSE_ORG_CONTENT_REPO or ASPOSE_ORG_CONTENT."
    )


def _dirty_files_in_content_repo(content_root: Path) -> set[str]:
    """Relative paths (POSIX-style, matching git's own output) of files with
    pre-existing uncommitted changes, per the plan §6 overlap-detection rule."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=content_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        print(
            f"WARNING: could not read git status in content repo ({e}); "
            "treating overlap set as unknown/empty.",
            file=sys.stderr,
        )
        return set()
    dirty = set()
    for line in result.stdout.splitlines():
        if len(line) > 3:
            dirty.add(line[3:].strip())
    return dirty


def _patch_headings(body: str, locale: str, registry: TemplateStringRegistry) -> tuple[str, int]:
    """Return (new_body, n_replaced)."""
    n_replaced = 0

    def _sub(m: re.Match) -> str:
        nonlocal n_replaced
        hashes, ws, text = m.group(1), m.group(2), m.group(3)
        value = registry.lookup(text.strip(), locale)
        if value is None:
            return m.group(0)
        n_replaced += 1
        return f"{hashes}{ws}{value}"

    new_body = _HEADING_RE.sub(_sub, body)
    return new_body, n_replaced


def run(
    sites: list[str],
    locales: list[str],
    apply: bool,
    max_files: int,
    registry_dir: Path | None,
    manifest_path: Path | None = None,
) -> list[str]:
    """Returns the list of content-repo-relative paths this run actually
    wrote (empty in --dry-run mode). Callers MUST commit using exactly this
    list (e.g. `git commit -- <paths>`), never a broad `git add`, since
    other sessions may have unrelated changes already staged in the same
    working tree/index (confirmed to happen live during this mission)."""
    content_root = _resolve_content_root()
    registry = TemplateStringRegistry(registry_dir) if registry_dir else TemplateStringRegistry()

    dirty_files = _dirty_files_in_content_repo(content_root) if apply else set()

    total_files_scanned = 0
    total_files_with_hits = 0
    total_headings_replaced = 0
    total_quarantined = 0
    overlap_flagged: list[str] = []
    written_paths: list[str] = []

    for site in sites:
        site_root = content_root / site
        if not site_root.exists():
            print(f"  SKIP site {site} (not found)")
            continue
        en_root = site_root / EN_LOCALE
        if not en_root.exists():
            continue

        en_files = list(en_root.rglob("*.md"))
        print(f"Site: {site} ({len(en_files)} EN files)")

        for locale in locales:
            locale_root = site_root / locale
            if not locale_root.exists():
                continue
            n_this_locale = 0
            n_hits_this_locale = 0
            n_replaced_this_locale = 0

            for en_path in en_files:
                if max_files and n_this_locale >= max_files:
                    break
                rel = en_path.relative_to(en_root)
                tr_path = locale_root / rel
                if not tr_path.exists():
                    continue
                n_this_locale += 1
                total_files_scanned += 1

                try:
                    frontmatter, body, raw = safe_io.load(tr_path)
                except OSError:
                    continue

                new_body, n_replaced = _patch_headings(body, locale, registry)
                if n_replaced == 0:
                    continue

                n_hits_this_locale += 1
                n_replaced_this_locale += n_replaced
                total_files_with_hits += 1
                total_headings_replaced += n_replaced

                rel_posix = str(tr_path.relative_to(content_root)).replace("\\", "/")
                if rel_posix in dirty_files:
                    overlap_flagged.append(rel_posix)

                if not apply:
                    continue

                try:
                    en_frontmatter, en_body, en_raw = safe_io.load(en_path)
                except OSError:
                    continue

                result = safe_io.save(
                    src_path=en_path,
                    out_path=tr_path,
                    frontmatter=frontmatter,
                    body=new_body,
                    source_content=en_raw,
                    target_lang=locale,
                )
                if not result.written:
                    total_quarantined += 1
                    print(
                        f"  QUARANTINED: {rel_posix} -> {result.reasons}",
                        flush=True,
                    )
                else:
                    written_paths.append(rel_posix)

            print(
                f"  {locale}: {n_this_locale} scanned, {n_hits_this_locale} files with a "
                f"heading hit, {n_replaced_this_locale} headings replaced",
                flush=True,
            )

    print()
    print(
        f"TOTAL: {total_files_scanned} files scanned, {total_files_with_hits} files with "
        f"a heading hit, {total_headings_replaced} headings replaced"
    )
    if apply:
        print(f"Quarantined (write-gate rejected): {total_quarantined}")
    if overlap_flagged:
        print()
        print(
            f"PRE-EXISTING DIRTY FILES touched by this run ({len(overlap_flagged)}) — "
            "these already had unrelated uncommitted changes in the content repo before "
            "this healer ran. Their diff will contain BOTH this healer's heading fix AND "
            "the pre-existing change; verify each in isolation before considering this "
            "taskcard's diff complete:"
        )
        for f in overlap_flagged:
            print(f"  {f}")
    if not apply:
        print("\n(--dry-run: no files written)")

    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            "\n".join(written_paths) + ("\n" if written_paths else ""), encoding="utf-8"
        )
        print(f"\nManifest of {len(written_paths)} written file(s): {manifest_path}")

    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch existing English headings using the reviewed i18n table "
        "(no LLM/MT calls)."
    )
    parser.add_argument("--sites", type=str, default="reference.aspose.org")
    parser.add_argument("--locales", type=str, default="")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Explicit dry-run (default behavior)"
    )
    parser.add_argument("--max-files", type=int, default=0, help="Stop after N EN files per locale")
    parser.add_argument(
        "--registry-dir",
        type=str,
        default="",
        help="Override the template_strings directory (for tests)",
    )
    parser.add_argument(
        "--manifest-out",
        type=str,
        default="",
        help="Write the list of files actually written (one per line, "
        "content-repo-relative) to this path -- use it to scope the "
        "follow-up `git commit -- <paths>` precisely, since other sessions "
        "may have unrelated changes already staged in the same working tree.",
    )
    args = parser.parse_args()

    sites = (
        ALL_SITES
        if args.sites.strip().lower() == "all"
        else [s.strip() for s in args.sites.split(",") if s.strip()]
    )
    locales = (
        [loc.strip() for loc in args.locales.split(",") if loc.strip()]
        if args.locales
        else NON_LATIN_LOCALES
    )
    apply = args.apply and not args.dry_run
    registry_dir = Path(args.registry_dir) if args.registry_dir else None
    manifest_path = Path(args.manifest_out) if args.manifest_out else None

    print(f"Sites: {sites}")
    print(f"Locales: {locales}")
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print()

    run(sites, locales, apply, args.max_files, registry_dir, manifest_path)


if __name__ == "__main__":
    main()
