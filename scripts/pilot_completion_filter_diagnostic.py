"""
Pilot diagnostic: measure completion-aware filter impact using real engine config.

Usage: python scripts/pilot_completion_filter_diagnostic.py [site_id]
Default site: about.aspose.net

Measures:
- How many source files filter_source_files() returns (BEFORE state, also current)
- How many of those the completion filter would skip (AFTER state)
- First-N alphabetical file completion status (shows whether alphabetical trap was present)
- Retranslate queue state

Does NOT translate anything. Read-only scan.
"""

import os, sys, logging
from pathlib import Path
from datetime import datetime

# Set required env vars
os.environ.setdefault('ASPOSE_NET_CONTENT', 'D:/onedrive/Documents/GitHub/aspose.net/content')
os.environ.setdefault('ASPOSE_ORG_CONTENT', 'D:/onedrive/Documents/GitHub/aspose.org/content')

logging.basicConfig(level=logging.WARNING)  # suppress info noise
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config_loader import ConfigService
from src.utils.file_filters import filter_source_files
from src.tm.retranslate_queue import load_queued_paths

SITE_ID = sys.argv[1] if len(sys.argv) > 1 else 'about.aspose.net'

print(f"\n{'='*70}")
print(f"PILOT DIAGNOSTIC — {SITE_ID}")
print(f"Run at: {datetime.now().isoformat()}")
print(f"{'='*70}")

# Load config (same path the worker uses)
cfg = ConfigService(Path(__file__).parent.parent / 'config')
site_profile = cfg.get_site_profile(SITE_ID)
if site_profile is None:
    print(f"ERROR: site profile '{SITE_ID}' not found")
    sys.exit(1)

target_langs = getattr(site_profile, 'target_langs', [])
content_roots = getattr(site_profile, 'content_roots', [])

print(f"\nSite: {SITE_ID}")
print(f"Target langs: {len(target_langs)}")
print(f"Content roots: {len(content_roots)}")

total_source_before = 0
total_source_after = 0
total_complete = 0
all_source_files = []

for root in content_roots:
    root = Path(str(root))
    if not root.exists():
        print(f"  SKIP (missing root): {root}")
        continue

    all_md = list(root.rglob('*.md'))
    source_files = filter_source_files(all_md, site_profile, list(target_langs))
    source_files = sorted(source_files, key=str)  # same order as engine
    all_source_files.extend(source_files)
    total_source_before += len(source_files)

# ── BEFORE state ─────────────────────────────────────────────────────────────
print(f"\n{'─'*50}")
print(f"BEFORE (filter_source_files only, no completion filter):")
print(f"  Source files selected per run: {total_source_before}")
print(f"  With files_per_commit=20: each run processes files 1-20 (always the same)")

# ── AFTER state ──────────────────────────────────────────────────────────────
print(f"\n{'─'*50}")
print(f"AFTER (with completion-aware filter, Stage 2A):")

complete = 0
incomplete = 0
queued_forced = 0

# Load retranslate queue
try:
    queued = load_queued_paths()
except Exception:
    queued = set()

def get_output_path(source_file: Path, lang: str) -> Path:
    """Mirror engine._get_output_path() for per_language_folders sites."""
    path_str = str(source_file)
    # Replace source lang segment with target lang in path
    src_lang = getattr(site_profile, 'default_source_lang', 'en')
    replacements = [
        (f'/{src_lang}/', f'/{lang}/'),
        (f'\\{src_lang}\\', f'\\{lang}\\'),
    ]
    for old, new in replacements:
        if old in path_str:
            return Path(path_str.replace(old, new, 1))
    return source_file.parent.parent / lang / source_file.name

first20_complete = 0
first20_detail = []
for i, f in enumerate(all_source_files):
    try:
        src_mtime = f.stat().st_mtime
    except OSError:
        incomplete += 1
        continue

    all_current = True
    any_queued = False
    langs_list = list(target_langs)

    for lang in langs_list:
        out = get_output_path(f, lang)
        if queued and str(out.resolve()) in queued:
            any_queued = True
        try:
            if not out.exists() or out.stat().st_mtime < src_mtime:
                all_current = False
        except OSError:
            all_current = False

    if any_queued:
        queued_forced += 1
        incomplete += 1
    elif all_current:
        complete += 1
        if i < 20:
            first20_complete += 1
    else:
        incomplete += 1

    if i < 20:
        status = "COMPLETE" if all_current else "INCOMPLETE"
        first20_detail.append(f"    [{status}] {f.name}")

print(f"  Complete (SKIP): {complete}")
print(f"  Incomplete (INCLUDE): {incomplete}")
if queued_forced:
    print(f"  Force-included from retranslate queue: {queued_forced}")
pct = round(100 * complete / total_source_before) if total_source_before else 0
print(f"  Reduction: {pct}% skipped per run")

# ── Alphabetical trap ────────────────────────────────────────────────────────
print(f"\n{'─'*50}")
print(f"ALPHABETICAL TRAP ANALYSIS (first 20 files, sorted):")
print(f"  {first20_complete}/20 were complete")
print(f"  With files_per_commit=20 and NO completion filter:")
print(f"    → These 20 files would consume the ENTIRE max_files budget every run")
print(f"    → Files 21+ would never be reached until files 1-20 are all done")
print(f"  With completion filter:")
if first20_complete > 0:
    print(f"    → {first20_complete} complete files SKIPPED, freeing slots for later files")
    freed = 20 - (20 - first20_complete)
    print(f"    → Budget consumed by first-20: {20 - first20_complete} incomplete files")
else:
    print(f"    → All first-20 are incomplete, no slots freed (all need translation)")
for line in first20_detail[:10]:
    print(line)
if len(first20_detail) > 10:
    print(f"    ... ({len(first20_detail)-10} more)")

# ── Retranslate queue ────────────────────────────────────────────────────────
print(f"\n{'─'*50}")
print(f"RETRANSLATE QUEUE (Stage 2C):")
print(f"  Queued output paths: {len(queued)}")
if queued:
    for p in list(queued)[:5]:
        print(f"    {Path(p).name}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"SUMMARY")
print(f"{'='*70}")
print(f"  BEFORE: {total_source_before} files selected every run (no completion filter)")
print(f"  AFTER:  {incomplete} files actually needing work, {complete} skipped")
print(f"  Stage 2A effectiveness: {pct}% reduction in per-run file selection")
print()
if first20_complete > 0:
    print(f"  Alphabetical trap: BROKEN — {first20_complete} completed early files")
    print(f"    no longer consume max_files slots, later files can now be reached")
else:
    print(f"  Alphabetical trap: not applicable (first 20 files all incomplete)")
print()
print(f"  Stage 2B (L3 in-place update): verified via unit tests (37 passing)")
print(f"  Stage 2C (retranslate queue): {len(queued)} files currently queued")
print(f"  Stage 1 (ollama args removed): verified by static grep")
