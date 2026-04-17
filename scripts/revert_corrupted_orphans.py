"""Scan orphan recovery commits for code block corruption and revert affected files.

Usage:
    python scripts/revert_corrupted_orphans.py --scan          # dry-run: list corrupted files
    python scripts/revert_corrupted_orphans.py --revert        # revert corrupted files and commit
"""

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(r"D:\onedrive\Documents\GitHub\aspose.net")
SINCE = "2026-02-28"


def run_git(*args: str, cwd: Path = REPO) -> str:
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def count_code_blocks(text: str) -> int:
    return len(re.findall(r"^```", text, re.MULTILINE)) // 2


def count_headings(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s", text, re.MULTILINE))


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:]
    return text


def get_orphan_commits():
    """Get all Hugo Translator commits since SINCE (orphan + regular)."""
    log = run_git(
        "log", "--oneline", "--format=%H", "--all",
        "--grep=Hugo Translator", f"--since={SINCE}",
    )
    return [h.strip() for h in log.splitlines() if h.strip()]


def get_commit_files(commit_hash: str):
    """Get list of files changed in a commit."""
    diff = run_git("diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash)
    return [f.strip() for f in diff.splitlines() if f.strip()]


def get_file_at_commit(commit_hash: str, file_path: str) -> str:
    """Get file content at a specific commit."""
    return run_git("show", f"{commit_hash}:{file_path}")


def get_file_before_commit(commit_hash: str, file_path: str) -> str:
    """Get file content from the commit before."""
    return run_git("show", f"{commit_hash}~1:{file_path}")


def scan_commit(commit_hash: str):
    """Scan a commit for corrupted files. Returns list of (file_path, reason)."""
    corrupted = []
    files = get_commit_files(commit_hash)

    for fpath in files:
        if not fpath.endswith(".md"):
            continue

        try:
            current = get_file_at_commit(commit_hash, fpath)
        except RuntimeError:
            continue

        # Derive source file path
        # File-based: index.pl.md -> index.md
        fname = Path(fpath).name
        parts = fname.rsplit(".", 2)
        if len(parts) >= 3:
            source_name = parts[0] + "." + parts[-1]
            source_path = (Path(fpath).parent / source_name).as_posix()
        else:
            continue

        # Try to get source from main branch
        try:
            source = run_git("show", f"HEAD:{source_path}")
        except RuntimeError:
            continue

        source_body = strip_frontmatter(source)
        current_body = strip_frontmatter(current)

        src_cb = count_code_blocks(source_body)
        cur_cb = count_code_blocks(current_body)
        src_hd = count_headings(source_body)
        cur_hd = count_headings(current_body)

        reasons = []
        if src_cb > 0 and cur_cb < src_cb:
            reasons.append(f"code blocks: {src_cb}->{cur_cb}")
        if cur_hd >= src_hd + 3:
            reasons.append(f"heading surplus: {src_hd}->{cur_hd}")
        if current_body.lstrip().startswith("TITLE:"):
            reasons.append("TITLE: prefix")

        if reasons:
            corrupted.append((fpath, "; ".join(reasons)))

    return corrupted


def main():
    parser = argparse.ArgumentParser(description="Scan and revert corrupted orphan files")
    parser.add_argument("--scan", action="store_true", help="Scan only (dry run)")
    parser.add_argument("--revert", action="store_true", help="Revert corrupted files")
    args = parser.parse_args()

    if not args.scan and not args.revert:
        parser.print_help()
        return

    commits = get_orphan_commits()
    print(f"Found {len(commits)} orphan recovery commits since {SINCE}")

    all_corrupted = []  # (commit, file_path, reason)

    for commit in commits:
        subject = run_git("log", "--format=%s", "-1", commit)
        corrupted = scan_commit(commit)
        if corrupted:
            print(f"\n{commit[:10]} {subject}")
            for fpath, reason in corrupted:
                print(f"  CORRUPTED: {fpath} — {reason}")
                all_corrupted.append((commit, fpath, reason))

    print(f"\nTotal corrupted files: {len(all_corrupted)}")

    if args.revert and all_corrupted:
        print("\nReverting corrupted files...")
        reverted = []
        for commit, fpath, reason in all_corrupted:
            try:
                # Try to get previous version
                try:
                    prev_content = get_file_before_commit(commit, fpath)
                    # Restore via checkout from parent
                    run_git("checkout", f"{commit}~1", "--", fpath)
                    reverted.append(fpath)
                    print(f"  Reverted: {fpath}")
                except RuntimeError:
                    # File didn't exist before — remove it
                    full = REPO / fpath
                    if full.exists():
                        full.unlink()
                        run_git("add", fpath)
                        reverted.append(fpath)
                        print(f"  Removed: {fpath} (didn't exist before orphan commit)")
            except Exception as e:
                print(f"  FAILED to revert {fpath}: {e}")

        if reverted:
            # Stage and commit
            for f in reverted:
                run_git("add", f)

            msg = (
                f"fix(blog): revert {len(reverted)} corrupted orphan recovery files\n\n"
                f"Orphan recovery commits since {SINCE} introduced files with stripped\n"
                f"code blocks and/or hallucinated content. This commit restores the\n"
                f"previous versions of affected files.\n\n"
                f"Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
            )
            run_git("commit", "-m", msg)
            print(f"\nCommitted revert of {len(reverted)} files")
        else:
            print("\nNo files to revert")


if __name__ == "__main__":
    main()
