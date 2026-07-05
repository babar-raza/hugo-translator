"""Quick status check for active translation run."""
import json
import sys
from pathlib import Path

run_id = "aspose_org_multisite_20260704_004654"
base = Path(".local/evidences/reference.aspose.org") / run_id / "checkpoints"

shards = ["latin-a", "latin-b", "latin-c", "latin-d", "latin-e", "latin-f"]
grand_accepted = 0
grand_failed = 0
all_verdicts = {}

for shard in shards:
    cp_path = base / f"checkpoint.{shard}.json"
    if not cp_path.exists():
        continue
    with open(cp_path) as f:
        cp = json.load(f)
    accepted = cp.get("accepted", {})
    failed = cp.get("failed", {})
    grand_accepted += len(accepted)
    grand_failed += len(failed)
    for fail_data in failed.values():
        v = fail_data.get("verdict", "UNKNOWN") if isinstance(fail_data, dict) else "UNKNOWN"
        all_verdicts[v] = all_verdicts.get(v, 0) + 1

total = grand_accepted + grand_failed
rate = grand_accepted / total * 100 if total else 0.0

lines = [
    f"Run: {run_id}",
    f"Accepted: {grand_accepted}  Failed: {grand_failed}  Total: {total}",
    f"Accept rate: {rate:.1f}%",
    f"Failure verdicts: {json.dumps(all_verdicts)}",
]

# Show recent failures from latin-a
cp_a = base / "checkpoint.latin-a.json"
if cp_a.exists():
    with open(cp_a) as f:
        cp = json.load(f)
    failed = cp.get("failed", {})
    lines.append(f"\nRecent failures (latin-a, {len(failed)} total):")
    for iid, item in list(failed.items())[-15:]:
        rp = item.get("relative_path", item.get("source_path", "?"))
        if isinstance(rp, str) and "reference.aspose.org" in rp:
            rp = rp.split("reference.aspose.org")[-1].replace("\\", "/")[:60]
        loc = item.get("locale", "?")
        v = item.get("verdict", "?")
        retries = item.get("retry_count", 0)
        lines.append(f"  [{loc}] {rp}: {v} (retry={retries})")

sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
