"""Merge exclusive worker journals into canonical campaign ledgers."""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock

def rows(path: Path) -> list[dict]:
    if not path.is_file(): return []
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]

def encoded(items: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in items)

def merge(root: Path) -> dict[str, int]:
    journal_root = root / "journals"
    partitions = sorted(p for p in journal_root.iterdir() if p.is_dir()) if journal_root.is_dir() else []
    receipts = {str(row["output_path"]): row for row in rows(root / "acceptance_receipts.jsonl")}
    failures = rows(root / "failure_metadata.jsonl")
    failure_hashes = {hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest() for r in failures}
    heals: list[dict] = []; added = 0
    for partition in partitions:
        for row in rows(partition / "acceptance_receipts.jsonl"):
            output = str(row["output_path"]); previous = receipts.get(output)
            if previous and previous.get("receipt_sha256") != row.get("receipt_sha256"):
                raise RuntimeError(f"conflicting receipt during merge: {output}")
            if previous is None: receipts[output] = row; added += 1
        for row in rows(partition / "failure_metadata.jsonl"):
            digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if digest not in failure_hashes: failures.append(row); failure_hashes.add(digest)
        heals.extend(rows(partition / "heal_queue.jsonl"))
    with FileLock(root / "journal-merge.lock", timeout=30):
        atomic_write(root / "acceptance_receipts.jsonl", encoded(sorted(receipts.values(), key=lambda r: str(r["output_path"]))), fsync=True, create_parents=True)
        atomic_write(root / "failure_metadata.jsonl", encoded(failures), fsync=True, create_parents=True)
        if heals:
            with (root.parent / "heal_queue.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded(heals)); stream.flush(); os.fsync(stream.fileno())
        if partitions:
            archive = root / "journal_archive" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"); archive.mkdir(parents=True)
            for partition in partitions: partition.replace(archive / partition.name)
    return {"partitions": len(partitions), "receipts_added": added, "failures": len(failures), "heal_tickets": len(heals)}

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--campaign-id", required=True); parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns")); args=parser.parse_args()
    print(json.dumps(merge(args.ledger_root / args.campaign_id), sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
