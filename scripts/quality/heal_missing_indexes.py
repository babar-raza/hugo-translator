#!/usr/bin/env python3
"""
Heal missing _index.md files in reference.aspose.org for a given set of locales.

Usage:
  python scripts/quality/heal_missing_indexes.py --locales sr sv zh
  python scripts/quality/heal_missing_indexes.py --locales ar bg ca cs da de --model nllb_200_1.3b
  python scripts/quality/heal_missing_indexes.py --locales el es fa fi --model m2m100_418m
  python scripts/quality/heal_missing_indexes.py --dry-run --locales ja ms

Run after killing the corresponding shard; restart shard when done.
"""
import io
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# Content root resolution
_env_content = os.environ.get("ASPOSE_ORG_CONTENT", "").strip()
if not _env_content:
    _env_file = ROOT / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line.startswith("ASPOSE_ORG_CONTENT=") and not _line.startswith("#"):
                _env_content = _line.split("=", 1)[1].strip().strip('"').strip("'")
                break

CONTENT = Path(_env_content) if _env_content else Path("C:/Users/prora/OneDrive/Documents/GitHub/aspose.org/content")
print(f"[config] CONTENT root: {CONTENT}", flush=True)

SITE_ID = "reference.aspose.org"
SITE_ROOT = CONTENT / SITE_ID
EN_ROOT = SITE_ROOT / "en"

# Parse CLI args
locales = []
model_id = "nllb_200_1.3b"
dry_run = "--dry-run" in sys.argv
max_memory = 8000

args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--locales":
        i += 1
        while i < len(args) and not args[i].startswith("--"):
            locales.append(args[i])
            i += 1
    elif args[i] == "--model" and i + 1 < len(args):
        model_id = args[i + 1]
        i += 2
    elif args[i] == "--max-memory" and i + 1 < len(args):
        max_memory = int(args[i + 1])
        i += 2
    else:
        i += 1

if not locales:
    print("ERROR: --locales required. Example: --locales sr sv zh", flush=True)
    sys.exit(1)

print(f"Locales: {locales}", flush=True)
print(f"Model: {model_id}", flush=True)
print(f"Mode: {'DRY RUN' if dry_run else 'TRANSLATE'}", flush=True)

# Collect missing _index.md files
missing = []
for rel in sorted(p.relative_to(EN_ROOT) for p in EN_ROOT.rglob("_index.md")):
    src = EN_ROOT / rel
    for loc in locales:
        out = SITE_ROOT / loc / rel
        if not out.exists():
            missing.append((loc, src, rel))

print(f"\nFound {len(missing)} missing _index.md files.", flush=True)
if not missing:
    print("Nothing to do.")
    sys.exit(0)

from collections import Counter
by_loc = Counter(loc for loc, _, _ in missing)
for loc, cnt in sorted(by_loc.items(), key=lambda x: -x[1]):
    print(f"  {loc}: {cnt}")
print()

if dry_run:
    print("DRY RUN — exiting without translation.")
    sys.exit(0)

# Resource governor
from src.hardware.resource_governor import make_governor
import atexit
governor = make_governor(root=ROOT)
granted = governor.wait_for_slot("heal_index", model_id)
if not granted:
    print("Could not obtain GPU slot. Is another shard running?", flush=True)
    sys.exit(1)
atexit.register(governor.release_slot)

# Build engine
from src.utils.config_loader import ConfigService
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry
from src.tm.translation_memory import TranslationMemory
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM, L2_DB_NAME
from src.tm import lmdb_registry as _lmdb_reg
from src.translation_engine.engine import TranslationEngine

_lmdb_reg.set_project_root(ROOT)
config_service = ConfigService(str(ROOT / "config"))
registry = ModelRegistry(str(ROOT / "config/model_registry.yaml"))
model_loader = ModelLoader(registry=registry, device="cuda", max_memory_mb=max_memory)
l1 = L1Cache(max_size=50000)
l2 = L2PersistentTM(db_path=ROOT / "data/tm" / L2_DB_NAME)
tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)

engine = TranslationEngine(
    config_service=config_service,
    tm=tm,
    model_loader=model_loader,
    enable_validation=True,
    enable_telemetry=False,
    enable_terminology=False,
    batch_size=64,
    force_accept=False,
    model_id=model_id,
)
print("Engine ready.", flush=True)

# Process locale by locale
ok = 0
fail = 0
t0 = time.time()

for loc in locales:
    loc_items = [(src, rel) for l, src, rel in missing if l == loc]
    if not loc_items:
        continue
    print(f"\n=== {loc}: {len(loc_items)} files ===", flush=True)

    # Prewarm L1 from L2
    try:
        for e in list(l2.export_iter(SITE_ID, loc))[:5000]:
            l1.set(SITE_ID, "en", loc, e.source_text, e.translation)
    except Exception:
        pass

    for src, rel in loc_items:
        try:
            engine.translate_file(
                site_id=SITE_ID,
                file_path=src,
                target_langs=[loc],
                force=False,
            )
            out = SITE_ROOT / loc / rel
            if out.exists():
                print(f"  OK  {rel}", flush=True)
                ok += 1
            else:
                print(f"  FAIL (no output) {rel}", flush=True)
                fail += 1
        except Exception as e:
            print(f"  ERR {rel}: {str(e)[:120]}", flush=True)
            fail += 1

elapsed = time.time() - t0
print(f"\n=== Done: {ok} ok, {fail} fail in {elapsed:.0f}s ===", flush=True)
