"""Serialize receipt-backed content checkpoints without touching a shared Git index.

The default is a non-mutating snapshot/verification.  ``--execute`` is the
only mode that creates local content commits, and it delegates each exact
checkpoint group to aspose.org's governed S-76 isolated-index plumbing.  It never
pushes and never stages the shared checkout's index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.workers.campaign_manifest import CampaignManifest
from src.utils.file_lock import FileLock


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_blob(repo: Path, revision: str, path: str) -> str:
    return hashlib.sha256(subprocess.check_output(
        ["git", "show", f"{revision}:{path}"], cwd=repo, timeout=30,
    )).hexdigest()


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


def manifest_output_index(manifest: CampaignManifest) -> dict[str, tuple[str, str, str]]:
    """Map each manifest output to its (site, family, platform) ownership partition.

    The manifest already carries `family`/`platform` on every source -- these
    were previously re-derived from the output path string instead, via a
    locale-prefix heuristic (`len(segment) in {2, 5} and alphabetic`) meant to
    detect an inserted locale code (like `zh-Hans`). That heuristic collided
    with several real family names of the same shape -- `words`, `cells`,
    `email` are all 5-letter alphabetic strings -- and silently mis-grouped
    every output under them (found live 2026-09-17: a `words/net` receipt
    partitioned itself as family="net", platform="introducing-words-foss-net").
    Reading the authoritative field on the source is both simpler and
    correct by construction.
    """
    index: dict[str, tuple[str, str, str]] = {}
    for source in manifest.sources:
        group = (source.site_id, source.family, source.platform)
        for _locale, output in source.outputs.items():
            if output in index:
                raise ValueError(f"manifest duplicate output ownership: {output}")
            index[output] = group
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
        os.fsync(handle.fileno())


def committed_batch_counts_by_group(path: Path) -> dict[tuple[str, str, str], int]:
    """How many COMMITTED batches already exist for each group, for numbering."""
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in read_jsonl(path):
        if row.get("status") == "COMMITTED":
            group = row.get("group") or {}
            key = (str(group.get("subdomain")), str(group.get("family")), str(group.get("platform")))
            counts[key] += 1
    return counts


def existing_completed_receipts(path: Path) -> set[tuple[str, str]]:
    """Return output/receipt pairs already committed.

    Output paths alone are not durable completion identities: a failed or
    superseded acceptance may be regenerated at the same path with a new
    receipt and must receive a corrective commit.
    """
    completed: set[tuple[str, str]] = set()
    for row in read_jsonl(path):
        if row.get("status") == "COMMITTED":
            outputs = [str(item) for item in row.get("outputs", [])]
            hashes = [str(item) for item in row.get("receipt_hashes", [])]
            completed.update(zip(outputs, hashes))
    return completed


def recover_recorded_commits(repo: Path, ledger_path: Path) -> None:
    """Recover the commit-before-ledger crash window using a unique trailer."""
    latest = {}
    for row in read_jsonl(ledger_path):
        if row.get("batch_id"):
            latest[row["batch_id"]] = row
    for batch_id, row in latest.items():
        if row.get("status") == "COMMITTED":
            continue
        marker = f"Campaign-Batch: {batch_id}"
        matches = subprocess.check_output([
            "git", "log", "main", f"{row['base_sha']}..main", "--format=%H",
            "--fixed-strings", f"--grep={marker}",
        ], cwd=repo, text=True, timeout=30).splitlines()
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("duplicate Git commits for checkpoint identity")
        commit = matches[0]
        changed = subprocess.check_output([
            "git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit,
        ], cwd=repo, text=True, timeout=30).splitlines()
        hashes = row["output_hashes"]
        if set(changed) != set(row["outputs"]) or any(
            sha256_blob(repo, commit, path) != hashes[path] for path in row["outputs"]
        ):
            raise ValueError("recovery commit differs from receipt snapshot")
        append_jsonl(ledger_path, dict(row, status="COMMITTED", commit_sha=commit,
                                     recovered=True, post_commit_hash_verified=True,
                                     recorded_at=datetime.now(timezone.utc).isoformat()))


def summarize_batch(group: tuple[str, str, str], chunk: list[dict[str, Any]]) -> str:
    """A concise `subdomain/family/platform (locales)` summary for a commit subject."""
    subdomain, family, platform = group
    locales = sorted({str(row["target_lang"]) for row in chunk})
    locale_part = ", ".join(locales) if len(locales) <= 12 else f"{len(locales)} locales"
    return f"{subdomain}/{family}/{platform} ({locale_part})"


def build_commit_message(group: tuple[str, str, str], chunk: list[dict[str, Any]]) -> str:
    subject = f"content(translation): {summarize_batch(group, chunk)}"
    return (
        f"{subject}\n\n"
        "Professionalize-only zero-defect outputs, partitioned by subdomain/family/platform.\n"
        "Skills invoked: [S-76, S-HT-02]\n"
    )


def commit_group(
    *, content_repo: Path, paths: list[str], message: str, base_sha: str, co_author: str,
    session_id: str | None = None,
) -> tuple[int, str]:
    """Run the repository-owned S-76 command using an isolated temporary input set."""
    import tempfile

    tool = content_repo / "scripts/pipeline/commands/ops/git_plumb_commit.py"
    with tempfile.TemporaryDirectory(prefix="portfolio-receipts-") as temp:
        root = Path(temp)
        files = root / "files.txt"
        message_path = root / "message.txt"
        files.write_text("\n".join(paths) + "\n", encoding="utf-8")
        message_path.write_text(message, encoding="utf-8")
        cmd = [sys.executable, str(tool), "--files-from", str(files), "--message-file", str(message_path),
             "--skills", "S-76", "S-HT-02", "--plan", "receipt-backed portfolio checkpoint",
             "--branch", "main", "--base-sha", base_sha, "--co-author", co_author, "--no-push"]
        if session_id:
            cmd.extend(["--session-id", session_id])
        result = subprocess.run(
            cmd,
            cwd=content_repo, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
    return result.returncode, (result.stdout + "\n" + result.stderr)[-8000:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--content-repo", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument(
        "--min-batch-size", type=int, default=25,
        help="Minimum receipts a (site,family,platform) group must hold before it is committed. "
             "A qualifying group is committed in full as one batch -- never split into smaller "
             "fixed-size chunks, and never held back once the minimum is met.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--co-author", default="hugo-translator <hugo-translator@aspose.org>")
    parser.add_argument("--session-id", help="Explicit governed aspose.org S-76 session identity.")
    args = parser.parse_args(argv)
    if args.min_batch_size < 1:
        parser.error("--min-batch-size must be >= 1")
    manifest = CampaignManifest.load(args.manifest)
    # Covers snapshot, plumbing, and ledger append across scheduler/controller
    # invocations; the shared content index is never used as a mutex.
    lock_path = args.ledger_root / manifest.campaign_id / "receipt-commit.lock"
    with FileLock(lock_path, timeout=1):
        return reconcile(args, manifest)


def reconcile(args: argparse.Namespace, manifest: CampaignManifest) -> int:
    content_repo = args.content_repo.resolve()
    root = args.ledger_root / manifest.campaign_id
    batches_path = root / "commit_batches.jsonl"
    if args.execute:
        recover_recorded_commits(content_repo, batches_path)
    completed = existing_completed_receipts(batches_path)
    batch_counts = committed_batch_counts_by_group(batches_path)
    receipts = [
        receipt
        for receipt in read_jsonl(root / "acceptance_receipts.jsonl")
        if (str(receipt.get("output_path") or ""), receipt_digest(receipt)) not in completed
    ]
    index = manifest_output_index(manifest)
    verified = verified_receipts(receipts, content_repo=content_repo, output_index=index)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for receipt in verified:
        grouped[index[str(receipt["output_path"])]].append(receipt)
    base_sha = subprocess.check_output(["git", "rev-parse", "main"], cwd=content_repo, text=True).strip()
    planned = 0
    for group in sorted(grouped):
        rows = sorted(grouped[group], key=lambda row: str(row["output_path"]))
        if len(rows) < args.min_batch_size:
            continue  # never create an undersized checkpoint; leave a visible backlog.
        chunk = rows  # commit everything currently available in this group as one batch
        paths = [str(row["output_path"]) for row in chunk]
        message = build_commit_message(group, chunk)
        batch_id = hashlib.sha256("\n".join(receipt_digest(row) for row in chunk).encode()).hexdigest()
        message += f"\nCampaign-Batch: {batch_id}\n"
        record = {
            "campaign_id": manifest.campaign_id, "recorded_at": datetime.now(timezone.utc).isoformat(),
            "group": {"subdomain": group[0], "family": group[1], "platform": group[2]},
            "batch_number": batch_counts[group] + 1, "base_sha": base_sha,
            "outputs": paths, "receipt_hashes": [receipt_digest(row) for row in chunk],
            "batch_id": batch_id,
            "output_hashes": {row["output_path"]: row["output_sha256"] for row in chunk},
            "status": "VERIFIED", "planned": len(paths), "verified": len(paths), "staged": 0,
        }
        planned += len(paths)
        if args.execute:
            # Write-ahead evidence survives a crash after Git advances main.
            append_jsonl(batches_path, record)
            code, output = commit_group(
                content_repo=content_repo, paths=paths, message=message, base_sha=base_sha,
                co_author=args.co_author, session_id=args.session_id,
            )
            if code:
                record.update({"status": "FAILED", "error": output})
                append_jsonl(batches_path, record)
                print(json.dumps(record, indent=2))
                return code
            # main may have advanced again in another governed writer. Verify
            # OUR commit, not an unrelated branch tip observed afterwards.
            matches = re.findall(r"(?m)^commit_sha=([0-9a-f]{40,64})\s*$", output)
            if len(matches) != 1:
                record.update({"status": "FAILED", "error": "plumbing did not return one commit identity"})
                append_jsonl(batches_path, record)
                return 3
            commit_sha = matches[0]
            mismatches = [path for path, row in zip(paths, chunk)
                          if sha256_file(content_repo / path) != row["output_sha256"]
                          or sha256_blob(content_repo, commit_sha, path) != row["output_sha256"]]
            if mismatches:
                record.update({"status": "FAILED", "commit_sha": commit_sha, "error": f"post-commit hash mismatch: {mismatches}"})
                append_jsonl(batches_path, record)
                return 3
            record.update({"status": "COMMITTED", "staged": len(paths), "commit_sha": commit_sha, "post_commit_hash_verified": True})
            base_sha = commit_sha
            batch_counts[group] += 1
        if args.execute:
            append_jsonl(batches_path, record)
        print(json.dumps(record, indent=2))
    print(json.dumps({"verified_receipts": len(verified), "planned_checkpoint_outputs": planned, "pending_commit": len(verified) - planned}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
