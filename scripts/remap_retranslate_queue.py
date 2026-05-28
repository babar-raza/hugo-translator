"""One-shot script: remap D:/onedrive paths -> C:/Users/prora/OneDrive in retranslate_queue.jsonl
and purge stale test/temp artifacts."""
import json
import shutil
from pathlib import Path

Q = Path("data/retranslate_queue.jsonl")
BACKUP = Q.with_suffix(".jsonl.bak")

shutil.copy2(Q, BACKUP)
print(f"Backup written: {BACKUP}")

entries = [json.loads(l) for l in Q.open(encoding="utf-8") if l.strip()]
print(f"Before: {len(entries)} entries")

D_PREFIX = "D:/onedrive/Documents/GitHub"
C_PREFIX = "C:/Users/prora/OneDrive/Documents/GitHub"


def is_stale(path_str: str) -> bool:
    """Return True for temp/test-artifact entries that should be purged."""
    norm = path_str.replace("\\", "/")
    return "AppData/Local/Temp" in norm or "data/evidence/rbtw" in norm


def remap(path_str: str) -> str:
    norm = path_str.replace("\\", "/")
    if norm.lower().startswith(D_PREFIX.lower()):
        norm = C_PREFIX + norm[len(D_PREFIX):]
    # Restore Windows separators
    return norm.replace("/", "\\")


kept, remapped_count, purged = 0, 0, 0
out = []
for e in entries:
    raw = e["output_path"]
    if is_stale(raw):
        purged += 1
        continue
    new_path = remap(raw)
    if new_path != raw:
        e["output_path"] = new_path
        remapped_count += 1
    out.append(e)
    kept += 1

with Q.open("w", encoding="utf-8") as f:
    for e in out:
        f.write(json.dumps(e) + "\n")

print(f"After:  {len(out)} entries")
print(f"  remapped D->C: {remapped_count}")
print(f"  purged (temp/test): {purged}")
print(f"  unchanged: {kept - remapped_count}")
