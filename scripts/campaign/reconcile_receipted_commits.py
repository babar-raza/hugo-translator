"""Serialize receipt-backed content checkpoints without touching a shared Git index.

The default is a non-mutating snapshot/verification.  ``--execute`` is the
only mode that creates local content commits, and it delegates each exact
100-file group to aspose.org's governed S-76 isolated-index plumbing.  It never
pushes and never stages the shared checkout's index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.workers.campaign_manifest import CampaignManifest


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def all_gates_pass(receipt: dict[str, Any]) -> bool:
    gates = receipt.get("gate_results") or {}
    return bool(gates) and all(
        isinstance(gate, dict)
        and gate.get("passed") is True
        and str(gate.get("action", "")).lower() not in {"warn", "warning", "skip", "skipped", "unavailable", "exception"}
        and gate.get("error") is None
        for gate in gates.values()
    )


def receipt_digest(receipt: dict[str, Any]) -> str:
    return str(receipt.get("receipt_sha256") or hashlib.sha256(
        json.dumps(receipt, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest())


def group_for_output(site_id: str, output_path: str) -> tuple[str, str, str]:
    """Return the required subdomain/family/platform ownership partition."""
    parts = Path(output_path).as_posix().split("/")
    try:
        site_index = parts.index(site_id)
    except ValueError as exc:
        raise ValueError(f"output is outside declared site {site_id}: {output_path}") from exc
    tail = parts[site_index + 1 :]
    # Most roots are site/family/platform; localized roots insert a locale.
    if len(tail) >= 3 and len(tail[0]) in {2, 5} and tail[0].split("-")[0].isalpha():
        tail = tail[1:]
    if not tail:
        raise ValueError(f"cannot derive family from {output_path}")
    # Product landing pages legitimately have no platform directory.  Keep
    # them isolated from any real platform instead of guessing one.
    platform = tail[1] if len(tail) >= 2 and not Path(tail[1]).suffix else "_root"
    return site_id, tail[0], platform


def manifest_output_index(manifest: CampaignManifest) -> dict[str, tuple[str, str, str]]:
    index: dict[str, tuple[str, str, str]] = {}
    for source in manifest.sources:
        for _locale, output in source.outputs.items():
            if output in index:
                raise ValueError(f"manifest duplicate output ownership: {output}")
            index[output] = group_for_output(source.site_id, output)
    return index


def verified_receipts(
    receipts: list[dict[str, Any]], *, content_repo: Path, output_index: dict[str, tuple[str, str, str]]
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    verified: list[dict[str, Any]] = []
    for receipt in receipts:
        output = str(receipt.get("output_path") or "")
        if not output or output in seen:
            raise ValueError(f"duplicate or missing receipt ownership: {output or '<missing>'}")
        seen.add(output)
        if output not in output_index:
            raise ValueError(f"receipt output is not in manifest: {output}")
        target = (content_repo / output).resolve()
        if content_repo not in target.parents or not target.is_file():
            raise ValueError(f"receipted output missing from content repo: {output}")
        if sha256_file(target) != receipt.get("output_sha256"):
            raise ValueError(f"receipt/output sha256 mismatch: {output}")
        if not all_gates_pass(receipt):
            raise ValueError(f"receipt has non-passing validation gate: {output}")
        verified.append(receipt)
    return verified


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()


def existing_completed_outputs(path: Path) -> set[str]:
    completed: set[str] = set()
    for row in read_jsonl(path):
        if row.get("status") == "COMMITTED":
            completed.update(str(item) for item in row.get("outputs", []))
    return completed


def commit_group(*, content_repo: Path, paths: list[str], base_sha: str, co_author: str) -> tuple[int, str]:
    """Run the repository-owned S-76 command using an isolated temporary input set."""
    import tempfile

    tool = content_repo / "scripts/pipeline/commands/ops/git_plumb_commit.py"
    with tempfile.TemporaryDirectory(prefix="portfolio-receipts-") as temp:
        root = Path(temp)
        files = root / "files.txt"
        message = root / "message.txt"
        files.write_text("\n".join(paths) + "\n", encoding="utf-8")
        message.write_text(
            "content(portfolio): receipt-backed translation checkpoint\n\n"
            "Professionalize-only zero-defect outputs, partitioned by subdomain/family/platform.\n"
            "Skills invoked: [S-76, S-HT-02]\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(tool), "--files-from", str(files), "--message-file", str(message),
             "--skills", "S-76", "S-HT-02", "--plan", "receipt-backed portfolio checkpoint",
             "--branch", "main", "--base-sha", base_sha, "--co-author", co_author, "--no-push"],
            cwd=content_repo, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
    return result.returncode, (result.stdout + "\n" + result.stderr)[-8000:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--content-repo", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--co-author", default="Codex <codex@openai.com>")
    args = parser.parse_args(argv)
    if args.max_files != 100:
        raise SystemExit("receipt checkpoint cadence is fixed at 100 files")

    manifest = CampaignManifest.load(args.manifest)
    content_repo = args.content_repo.resolve()
    root = args.ledger_root / manifest.campaign_id
    batches_path = root / "commit_batches.jsonl"
    completed = existing_completed_outputs(batches_path)
    receipts = [r for r in read_jsonl(root / "acceptance_receipts.jsonl") if r.get("output_path") not in completed]
    index = manifest_output_index(manifest)
    verified = verified_receipts(receipts, content_repo=content_repo, output_index=index)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for receipt in verified:
        grouped[index[str(receipt["output_path"])]].append(receipt)
    base_sha = subprocess.check_output(["git", "rev-parse", "main"], cwd=content_repo, text=True).strip()
    planned = 0
    for group in sorted(grouped):
        rows = sorted(grouped[group], key=lambda row: str(row["output_path"]))
        for chunk_index in range(0, len(rows), args.max_files):
            chunk = rows[chunk_index : chunk_index + args.max_files]
            if len(chunk) < args.max_files:
                continue  # never create an undersized checkpoint; leave a visible backlog.
            paths = [str(row["output_path"]) for row in chunk]
            record = {
                "campaign_id": manifest.campaign_id, "recorded_at": datetime.now(timezone.utc).isoformat(),
                "group": {"subdomain": group[0], "family": group[1], "platform": group[2]},
                "batch_number": chunk_index // args.max_files + 1, "base_sha": base_sha,
                "outputs": paths, "receipt_hashes": [receipt_digest(row) for row in chunk],
                "status": "VERIFIED", "planned": len(paths), "verified": len(paths), "staged": 0,
            }
            planned += len(paths)
            if args.execute:
                code, output = commit_group(content_repo=content_repo, paths=paths, base_sha=base_sha, co_author=args.co_author)
                if code:
                    record.update({"status": "FAILED", "error": output})
                    append_jsonl(batches_path, record)
                    print(json.dumps(record, indent=2))
                    return code
                commit_sha = subprocess.check_output(["git", "rev-parse", "main"], cwd=content_repo, text=True).strip()
                mismatches = [path for path, row in zip(paths, chunk) if sha256_file(content_repo / path) != row["output_sha256"]]
                if mismatches:
                    record.update({"status": "FAILED", "commit_sha": commit_sha, "error": f"post-commit hash mismatch: {mismatches}"})
                    append_jsonl(batches_path, record)
                    return 3
                record.update({"status": "COMMITTED", "staged": len(paths), "commit_sha": commit_sha, "post_commit_hash_verified": True})
                base_sha = commit_sha
            append_jsonl(batches_path, record)
            print(json.dumps(record, indent=2))
    print(json.dumps({"verified_receipts": len(verified), "planned_checkpoint_outputs": planned, "pending_commit": len(verified) - planned}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
