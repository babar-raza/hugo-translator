# ARCHIVED: 2026-06-11. Sprint: completion-filter-diagnostic. STATUS: COMPLETE.
# No replacement needed — one-time measurement.
"""
Pilot measurement: completion-aware filter impact.
Compares BEFORE (raw filter_source_files count) vs AFTER (with completion-aware filter).
Run: python scripts/pilot_measure_completion_filter.py [site_profile_yaml]
"""

import os
import sys
from pathlib import Path

import yaml

os.environ.setdefault("ASPOSE_NET_CONTENT", "D:/onedrive/Documents/GitHub/aspose.net/content")
os.environ.setdefault("ASPOSE_ORG_CONTENT", "D:/onedrive/Documents/GitHub/aspose.org/content")


# resolve env vars in a yaml string value
def expand(s):
    for k, v in os.environ.items():
        s = s.replace("${" + k + "}", v)
    return s


sys.path.insert(0, ".")
from src.utils.file_filters import filter_source_files

profile_path = sys.argv[1] if len(sys.argv) > 1 else "config/site_profiles/about.aspose.net.yaml"
with open(profile_path) as f:
    raw = yaml.safe_load(f)

target_langs = raw["target_langs"]
site_id = raw.get("site_id", profile_path)
localization = raw.get("localization_strategy", "per_language_folders")

print(f"\n=== Pilot: {site_id} ===")
print(f"Localization: {localization}")
print(f"Target langs: {len(target_langs)}")

for cr_str in raw.get("content_roots", []):
    cr_str = expand(cr_str)
    root = Path(cr_str)
    if not root.exists():
        print(f"  SKIP (missing): {root}")
        continue

    all_md = list(root.rglob("*.md"))
    source_files = filter_source_files(all_md, raw, target_langs)

    print(f"\n  Content root: {root.name}  ({len(all_md)} total .md)")
    print(f"  BEFORE (filter_source_files only): {len(source_files)} source files per lang")

    complete = 0
    incomplete = 0
    queued_override = 0

    for f in source_files:
        try:
            src_mtime = f.stat().st_mtime
        except OSError:
            incomplete += 1
            continue

        all_current = True
        for lang in target_langs:
            if localization == "per_language_folders":
                # Replace /en/ segment with /{lang}/ in absolute path
                parts = list(f.parts)
                try:
                    en_idx = parts.index("en")
                    parts[en_idx] = lang
                    out = Path(*parts)
                except ValueError:
                    out = f.parent.parent / lang / f.name
            elif localization in ("per_file", "per_file_localization"):
                out = f.parent / f"{f.stem}.{lang}{f.suffix}"
            else:
                out = f.parent.parent / lang / f.name

            try:
                if not out.exists() or out.stat().st_mtime < src_mtime:
                    all_current = False
                    break
            except OSError:
                all_current = False
                break

        if all_current:
            complete += 1
        else:
            incomplete += 1

    pct = round(100 * complete / len(source_files)) if source_files else 0
    print(
        f"  AFTER  (with completion filter):   {incomplete} include, {complete} skip ({pct}% skipped)"
    )
    print(f"  Net savings per daemon run: {complete} file-translate calls avoided")
    if complete > 0:
        print("  Alphabetical trap status: ", end="")
        # Check if first 20 are complete (old behaviour would re-process them every run)
        first20 = source_files[:20]
        first20_complete = 0
        for f in first20:
            try:
                src_mtime = f.stat().st_mtime
            except OSError:
                continue
            all_c = True
            for lang in target_langs:
                if localization == "per_language_folders":
                    parts = list(f.parts)
                    try:
                        en_idx = parts.index("en")
                        parts[en_idx] = lang
                        out = Path(*parts)
                    except ValueError:
                        out = f.parent.parent / lang / f.name
                elif localization in ("per_file", "per_file_localization"):
                    out = f.parent / f"{f.stem}.{lang}{f.suffix}"
                else:
                    out = f.parent.parent / lang / f.name
                try:
                    if not out.exists() or out.stat().st_mtime < src_mtime:
                        all_c = False
                        break
                except OSError:
                    all_c = False
                    break
            if all_c:
                first20_complete += 1
        print(
            f"{first20_complete}/20 of alphabetically-first files were complete (previously consumed max_files slots every run)"
        )
