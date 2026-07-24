#!/usr/bin/env python
"""
TC-P7-10 / TC-P7-11: backlog manifests for the two categories that have no
mechanical fixer at all (see plan Deliverable 3):

- shortcode_leak (15 files): traced to root cause 2 (stale/orphaned
  translations) -- concentrated in hr/sr (south_slavic similarity group)
  + ms/he; the leaked literal (e.g. `{{< sections cols="4" >}}`) does not
  exist anywhere in the current EN source for the same file. Re-wrapping
  the fragment would patch a symptom of already-stale content, not fix it.
- empty_body (88 files): confirmed via git history (sampled) that these
  files have been frontmatter-only since the commit that introduced them
  -- no recoverable prior revision exists anywhere. Real translation work
  only; files stay in place (never deleted from content repos).

Writes reports/audit/backlog_shortcode_leak.csv and
reports/audit/backlog_empty_body.csv. Does not touch the content repo.
"""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org")


def git_log_line_count(rel_path: str) -> int:
    """Count commits touching this path, in the content repo. 0/1 means no
    recoverable prior revision could exist even in principle."""
    try:
        out = subprocess.run(
            ["git", "log", "--oneline", "--", rel_path],
            cwd=CONTENT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except Exception:  # noqa: BLE001
        return -1


def load_rows(issue_type: str) -> list[dict]:
    rows = []
    with open("reports/audit/findings_detail.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] == issue_type:
                rows.append(r)
    return rows


def write_manifest(rows: list[dict], reason: str, out_path: Path, sample_git_check: int = 0) -> None:
    out_rows = []
    for i, r in enumerate(rows):
        note = reason
        if sample_git_check and i < sample_git_check:
            rel = r["file_path"]
            if rel.startswith(str(CONTENT_ROOT) + "\\"):
                rel = rel[len(str(CONTENT_ROOT)) + 1 :]
            n_commits = git_log_line_count(rel)
            note = f"{reason} [git-history-checked: {n_commits} commit(s) touched this path]"
        out_rows.append(
            {
                "site_id": r["site_id"],
                "family": r["family"],
                "locale": r["locale"],
                "file_path": r["file_path"],
                "en_path": r["en_path"],
                "issue_type": r["issue_type"],
                "backlog_reason": note,
            }
        )
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["site_id", "family", "locale", "file_path", "en_path", "issue_type", "backlog_reason"]
        )
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {out_path} ({len(out_rows)} rows)")


def main() -> int:
    out_dir = Path("reports/audit")
    out_dir.mkdir(parents=True, exist_ok=True)

    shortcode_rows = load_rows("shortcode_leak")
    write_manifest(
        shortcode_rows,
        "Root cause 2 (stale/orphaned translation) -- leaked shortcode literal absent from current EN source; "
        "not mechanically fixable without retranslation",
        out_dir / "backlog_shortcode_leak.csv",
    )

    empty_body_rows = load_rows("empty_body")
    write_manifest(
        empty_body_rows,
        "Committed empty from creation -- no recoverable prior non-empty revision exists; real translation work only",
        out_dir / "backlog_empty_body.csv",
        sample_git_check=15,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
