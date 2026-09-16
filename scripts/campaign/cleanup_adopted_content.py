"""Commit only paths already adopted into a governed aspose.org session."""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--exclude-receipts", type=Path,
                   help="Campaign acceptance_receipts.jsonl; receipt-owned paths are left to the campaign reconciler.")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Maximum legacy-cleanup files per commit (default: 100).")
    p.add_argument("--min-files", type=int, default=5,
                   help="Hard minimum files per cleanup commit (default: 5).")
    args = p.parse_args()
    if args.batch_size < args.min_files or args.min_files < 5:
        raise ValueError("cleanup commits require min-files >= 5 and batch-size >= min-files")
    repo = args.repo.resolve()
    excluded: set[str] = set()
    if args.exclude_receipts and args.exclude_receipts.is_file():
        import json
        excluded = {
            str(json.loads(line).get("output_path"))
            for line in args.exclude_receipts.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("output_path")
        }
    ledger = repo / "scripts/pipeline/commands/ops/session_ledger.py"
    listed = subprocess.check_output(
        [sys.executable, str(ledger), "list", "--session-id", args.session_id, "--format", "paths"],
        cwd=repo, text=True,
    )
    adopted = {line.strip() for line in listed.splitlines() if line.strip().startswith("content/")}
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", "content"],
        cwd=repo, text=True,
    )
    dirty = {line[3:].strip() for line in status.splitlines() if len(line) >= 4 and line[:2] in {"??", " M", "M "}}
    groups: dict[str, list[str]] = {}
    blocked: list[str] = []
    for path in sorted((adopted & dirty) - excluded):
        try:
            if "\ufffd" in (repo / path).read_text(encoding="utf-8"):
                blocked.append(path)
                continue
        except (OSError, UnicodeError):
            blocked.append(path)
            continue
        parts = path.split("/")
        # Localized content is content/site/locale/family/platform/... .
        # Group across locales but retain the site/family/platform boundary,
        # preventing locale-sized one-file commit spam.
        tail = parts[2:]
        if tail and len(tail[0]) in {2, 5} and tail[0].split("-")[0].isalpha():
            tail = tail[1:]
        group = "/".join([*parts[:2], *(tail[:2] or ["_root"])])
        groups.setdefault(group, []).append(path)
    print(f"ADOPTED_DIRTY {sum(map(len, groups.values()))} GROUPS {len(groups)} BLOCKED_ENCODING {len(blocked)}", flush=True)
    for path in blocked:
        print(f"BLOCKED_ENCODING {path}", flush=True)
    for group, paths in sorted(groups.items()):
        for offset in range(0, len(paths), args.batch_size):
            batch = paths[offset:offset + args.batch_size]
            if len(batch) < args.min_files:
                print(f"DEFER_UNDERSIZED {group} {len(batch)} minimum={args.min_files}", flush=True)
                continue
            print(f"RUN {group} {len(batch)}", flush=True)
            with tempfile.TemporaryDirectory(prefix="aspose-content-") as td:
                root = Path(td)
                files = root / "files.txt"
                message = root / "message.txt"
                files.write_text("\n".join(batch) + "\n", encoding="utf-8")
                message.write_text(
                    f"content(translation): prior translated {group} batch\n\n"
                    f"Receipt provenance: pre-existing translated content adopted into governed S-76 session {args.session_id}.\n"
                    "Skills invoked: [S-76, S-HT-02]\n"
                    "Co-authored-by: Codex <codex@openai.com>\n",
                    encoding="utf-8",
                )
                cmd = [
                    sys.executable,
                    str(repo / "scripts/pipeline/commands/ops/git_plumb_commit.py"),
                    "--files-from", str(files), "--message-file", str(message),
                    "--skills", "S-76", "S-HT-02", "--plan", "prior translated content cleanup",
                    "--branch", "main", "--session-id", args.session_id,
                    "--co-author", "Codex <codex@openai.com>", "--no-push",
                ]
                result = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, encoding="utf-8", errors="replace")
                print(f"RC {result.returncode}\n{(result.stdout + result.stderr)[-2000:]}", flush=True)
                if result.returncode:
                    return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
