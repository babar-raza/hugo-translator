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

Modes (reference-i18n-hardening-20260725, plan item C1):
  --mode normalize (default, original TC-HT-I18N-007 behavior): replace ANY
    heading matching a registry EN term with the current approved locale
    value, regardless of what the existing translated text is. This
    normalizes every acceptable-but-inconsistent variant too (e.g. a ja
    "See Also" file using "参照" gets rewritten to the approved "関連情報"
    even though "参照" is itself a fine translation) — high consistency,
    higher churn/risk. Kept available, not the default going forward.
  --mode targeted (recommended, plan-approved default posture): replace a
    heading ONLY when it is a PROVEN defect: (i) English leakage (the
    current text literally equals the EN term), (ii) an adjudicated
    `rejected_variants` entry for that (term, locale) — i.e. a corpus form
    a reviewer explicitly confirmed wrong — or (iii) an identifier-heading
    restoration (the EN counterpart heading is protected/multi-hump-shaped
    and the locale heading differs from it — e.g. `## ImageRenderOptions`
    mistranslated in ja/lt — restored to the EN text verbatim). Acceptable
    variant forms are left untouched; they converge over time via the
    i18n-first live pipeline (TC-HT-I18N-004 / reference-i18n-hardening-
    20260725's Step-0 pre-TM pass) on next regeneration, per the
    plan's healing-scope decision (D1).
    Identifier restoration requires reading the EN counterpart file for
    positional alignment (equal-count zip only, same as the miner's fast
    path); files whose EN/locale heading counts differ are skipped for
    that specific check (counted, not silently ignored) but still get the
    leakage/rejected-variant checks applied.

Usage:
  python scripts/quality/heal_english_headings_dictionary.py --dry-run --sites all
  python scripts/quality/heal_english_headings_dictionary.py --mode targeted --apply --sites reference.aspose.org --locales ja --max-files 20
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
    _MULTI_HUMP_RE,
    TemplateStringRegistry,
)

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"
NON_LATIN_LOCALES = ["ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh"]
VALID_MODES = ("normalize", "targeted")

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


def _patch_headings(
    body: str,
    locale: str,
    registry: TemplateStringRegistry,
    *,
    mode: str = "normalize",
    en_body: str | None = None,
) -> tuple[str, int, dict[str, int]]:
    """Return (new_body, n_replaced, reasons). ``reasons`` counts by fix
    type: normalize | leakage | rejected_variant | identifier_restore."""
    reasons = {"normalize": 0, "leakage": 0, "rejected_variant": 0, "identifier_restore": 0}

    if mode == "normalize":
        n_replaced = 0

        def _sub_normalize(m: re.Match) -> str:
            nonlocal n_replaced
            hashes, ws, text = m.group(1), m.group(2), m.group(3)
            stripped = text.strip()
            value = registry.lookup(stripped, locale)
            if value is None or value == stripped:
                return m.group(0)
            n_replaced += 1
            reasons["normalize"] += 1
            return f"{hashes}{ws}{value}"

        new_body = _HEADING_RE.sub(_sub_normalize, body)
        return new_body, n_replaced, reasons

    # mode == "targeted"
    locale_matches = list(_HEADING_RE.finditer(body))
    en_headings: list[str] | None = None
    if en_body is not None:
        en_matches = [m.group(3).strip() for m in _HEADING_RE.finditer(en_body)]
        if len(en_matches) == len(locale_matches):
            en_headings = en_matches  # equal-count: positional alignment is safe

    n_replaced = 0
    idx = -1

    def _sub_targeted(m: re.Match) -> str:
        nonlocal n_replaced, idx
        hashes, ws, text = m.group(1), m.group(2), m.group(3)
        idx += 1
        stripped = text.strip()

        # (i) English leakage: current text literally IS the EN registry term.
        value = registry.lookup(stripped, locale)
        if value is not None and value != stripped:
            n_replaced += 1
            reasons["leakage"] += 1
            return f"{hashes}{ws}{value}"

        if en_headings is not None:
            en_text = en_headings[idx]

            # (ii) adjudicated rejected_variants for the EN heading THIS
            # locale heading is translating (requires knowing which entry
            # via positional alignment -- the wrong form itself carries no
            # EN text to look up by).
            rejected = registry.rejected_variants_for_text(en_text, locale)
            if stripped in rejected:
                approved = registry.lookup(en_text, locale)
                if approved is not None:
                    n_replaced += 1
                    reasons["rejected_variant"] += 1
                    return f"{hashes}{ws}{approved}"

            # (iii) identifier-heading restoration: the EN heading is a
            # protected multi-hump identifier (e.g. ImageRenderOptions) and
            # the locale heading was mistranslated away from it -- restore
            # EN verbatim. Single-hump words are deliberately NOT covered
            # here (shape alone can't tell heading-word from class-name;
            # that ambiguity is exactly why classification.py never decides
            # single-hump words by shape either).
            if _MULTI_HUMP_RE.match(en_text) and stripped != en_text:
                n_replaced += 1
                reasons["identifier_restore"] += 1
                return f"{hashes}{ws}{en_text}"

        return m.group(0)

    new_body = _HEADING_RE.sub(_sub_targeted, body)
    return new_body, n_replaced, reasons


def run(
    sites: list[str],
    locales: list[str],
    apply: bool,
    max_files: int,
    registry_dir: Path | None,
    manifest_path: Path | None = None,
    mode: str = "normalize",
    families: list[str] | None = None,
) -> list[str]:
    """Returns the list of content-repo-relative paths this run actually
    wrote (empty in --dry-run mode). Callers MUST commit using exactly this
    list (e.g. `git commit -- <paths>`), never a broad `git add`, since
    other sessions may have unrelated changes already staged in the same
    working tree/index (confirmed to happen live during this mission)."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    content_root = _resolve_content_root()
    registry = TemplateStringRegistry(registry_dir) if registry_dir else TemplateStringRegistry()

    dirty_files = _dirty_files_in_content_repo(content_root) if apply else set()

    total_files_scanned = 0
    total_files_with_hits = 0
    total_headings_replaced = 0
    total_quarantined = 0
    overlap_flagged: list[str] = []
    written_paths: list[str] = []
    reasons_total = {"normalize": 0, "leakage": 0, "rejected_variant": 0, "identifier_restore": 0}
    misaligned_files = 0  # targeted mode: EN/locale heading count differs -> no identifier-restore/rejected-variant check for that file

    for site in sites:
        site_root = content_root / site
        if not site_root.exists():
            print(f"  SKIP site {site} (not found)")
            continue
        en_root = site_root / EN_LOCALE
        if not en_root.exists():
            continue

        en_files = list(en_root.rglob("*.md"))
        if families:
            en_files = [
                p
                for p in en_files
                if (parts := p.relative_to(en_root).parts) and parts[0] in families
            ]
        print(
            f"Site: {site} ({len(en_files)} EN files"
            + (f", families={families}" if families else "")
            + ")"
        )

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

                en_body_for_alignment = None
                if mode == "targeted":
                    try:
                        _, en_body_for_alignment, _ = safe_io.load(en_path)
                    except OSError:
                        en_body_for_alignment = None

                new_body, n_replaced, reasons = _patch_headings(
                    body, locale, registry, mode=mode, en_body=en_body_for_alignment
                )
                for k, v in reasons.items():
                    reasons_total[k] += v
                if (
                    mode == "targeted"
                    and en_body_for_alignment is not None
                    and len(list(_HEADING_RE.finditer(body)))
                    != len(list(_HEADING_RE.finditer(en_body_for_alignment)))
                ):
                    misaligned_files += 1
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
    if mode == "targeted":
        print(
            f"  by reason: leakage={reasons_total['leakage']} "
            f"rejected_variant={reasons_total['rejected_variant']} "
            f"identifier_restore={reasons_total['identifier_restore']}"
        )
        print(
            f"  files with EN/locale heading-count mismatch (rejected_variant/"
            f"identifier_restore skipped for those files, leakage still applied): "
            f"{misaligned_files}"
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


def _target_langs_for_site(site: str) -> list[str]:
    """Read target_langs from config/site_profiles/<site>.yaml (mirrors
    mine_heading_glossary.py's identical helper) -- used by --locales all."""
    import yaml

    repo_root = Path(__file__).resolve().parent.parent.parent
    profile_path = repo_root / "config" / "site_profiles" / f"{site}.yaml"
    if not profile_path.exists():
        return list(NON_LATIN_LOCALES)
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    langs = data.get("target_langs") or []
    return [str(lang) for lang in langs]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch existing English headings using the reviewed i18n table "
        "(no LLM/MT calls)."
    )
    parser.add_argument("--sites", type=str, default="reference.aspose.org")
    parser.add_argument("--locales", type=str, default="")
    parser.add_argument(
        "--families",
        type=str,
        default="",
        help="Comma list of product-family top-level dirs to restrict scanning to "
        "(e.g. 'note' for a small pilot slice); default: all families under the site.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="normalize",
        choices=list(VALID_MODES),
        help="normalize (original behavior: force every matched heading to the "
        "current approved value) or targeted (recommended: only fix proven "
        "defects -- English leakage, adjudicated rejected_variants, identifier "
        "restoration; leave acceptable variant forms untouched). See module "
        "docstring for the full rationale.",
    )
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
    if args.locales.strip().lower() == "all":
        locales = sorted({lang for site in sites for lang in _target_langs_for_site(site)})
    elif args.locales:
        locales = [loc.strip() for loc in args.locales.split(",") if loc.strip()]
    else:
        locales = list(NON_LATIN_LOCALES)
    families = [f.strip() for f in args.families.split(",") if f.strip()] or None
    apply = args.apply and not args.dry_run
    registry_dir = Path(args.registry_dir) if args.registry_dir else None
    manifest_path = Path(args.manifest_out) if args.manifest_out else None

    print(f"Sites: {sites}")
    print(f"Locales: {locales}")
    print(f"Families: {families or 'all'}")
    print(f"Mode: {args.mode} ({'APPLY' if apply else 'DRY-RUN'})")
    print()

    run(
        sites,
        locales,
        apply,
        args.max_files,
        registry_dir,
        manifest_path,
        mode=args.mode,
        families=families,
    )


if __name__ == "__main__":
    main()
