"""Git-commit provenance forensics for translated outputs (TC-APT-003, plan section 7.4).

Factored out of ``campaign_runner.CampaignRunner._receipt_recovery_candidates`` so the
provenance backfill and the runner's receipt recovery share ONE definition of
"governed commit provenance".  The rules are unchanged from the runner:

1. the path's latest commit must be reachable from ``HEAD``;
2. that commit must be *after* the pinned content baseline (baseline is its ancestor);
3. its subject must match the governed pattern (``content(locale): zero-defect shard
   w<wave>:<site>:<family>:<platform>:<locale>:<n>``);
4. it must be a **one-file add** commit (``A\\t<path>`` and nothing else);
5. the current bytes must equal the committed blob.

Anything else is NOT governed provenance -- deliberately, so arbitrary pre-existing
files can never be mistaken for receipted output.

The bulk helper :func:`last_add_commits` walks history once (``git log --diff-filter=A``)
instead of one subprocess per path, which is what makes a 100k-file backfill feasible.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class GovernedProvenanceError(RuntimeError):
    """The path's git history does not constitute governed provenance."""


@dataclass(frozen=True)
class GovernedCommit:
    relative_path: str
    commit_sha: str
    subject: str
    blob_sha256: str


def governed_subject_pattern(
    *, wave: int, site_id: str, family: str, platform: str, locale: str
) -> re.Pattern[str]:
    shard_prefix = f"w{wave}:{site_id}:{family}:{platform}:{locale}:"
    return re.compile(
        rf"^content\(locale\): zero-defect shard {re.escape(shard_prefix)}[1-9][0-9]*$"
    )


def _run(
    repo: Path, args: list[str], *, check: bool = True, text: bool = False
) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=text)


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        _run(repo, ["merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode
        == 0
    )


def last_path_commit(repo: Path, relative: str) -> tuple[str, str] | None:
    """``(sha, subject)`` of the latest commit touching ``relative``, or None."""
    log = (
        _run(repo, ["log", "-1", "--format=%H%x00%s", "--", relative])
        .stdout.decode("utf-8", errors="strict")
        .strip()
    )
    if "\0" not in log:
        return None
    sha, subject = log.split("\0", 1)
    return sha, subject


def commit_changes(repo: Path, commit_sha: str) -> list[str]:
    """``name-status`` lines of a commit (e.g. ``['A\\tcontent/x.md']``)."""
    return _run(
        repo, ["diff-tree", "--no-commit-id", "--name-status", "-r", commit_sha], text=True
    ).stdout.splitlines()


def blob_sha256(repo: Path, commit_sha: str, relative: str) -> str:
    return hashlib.sha256(_run(repo, ["show", f"{commit_sha}:{relative}"]).stdout).hexdigest()


def verify_governed_add(
    repo: Path,
    relative: str,
    *,
    subject_pattern: re.Pattern[str],
    baseline_sha: str,
    current_sha256: str,
    last_commit: tuple[str, str] | None = None,
) -> GovernedCommit:
    """Apply the five governed-provenance rules; raise :class:`GovernedProvenanceError` otherwise.

    ``last_commit`` may be supplied from a bulk :func:`last_add_commits` pass to avoid a
    per-path ``git log``.  Error messages mirror the runner's historical wording so its
    callers/tests keep the same diagnostics.
    """
    found = last_commit if last_commit is not None else last_path_commit(repo, relative)
    if found is None:
        raise GovernedProvenanceError(f"receipt recovery path has no commit provenance: {relative}")
    commit_sha, subject = found
    if not subject_pattern.fullmatch(subject):
        raise GovernedProvenanceError(f"receipt recovery commit is not governed: {relative}")
    if not is_ancestor(repo, baseline_sha, commit_sha):
        raise GovernedProvenanceError(
            f"receipt recovery commit predates pinned baseline: {relative}"
        )
    if not is_ancestor(repo, commit_sha, "HEAD"):
        raise GovernedProvenanceError(f"receipt recovery commit is not reachable: {relative}")
    if commit_changes(repo, commit_sha) != [f"A\t{relative}"]:
        raise GovernedProvenanceError(
            f"receipt recovery requires a one-file add commit: {relative}"
        )
    committed = blob_sha256(repo, commit_sha, relative)
    if committed != current_sha256:
        raise GovernedProvenanceError(f"receipt recovery blob drift: {relative}")
    return GovernedCommit(
        relative_path=relative, commit_sha=commit_sha, subject=subject, blob_sha256=committed
    )


def last_add_commits(repo: Path, paths: Iterable[str] | None = None) -> dict[str, tuple[str, str]]:
    """Map ``relative_path -> (sha, subject)`` of the LATEST commit that ADDED each path.

    One history walk (newest first, ``--diff-filter=A``); the first time a path is seen is
    its most recent add.  Restricting to ``paths`` filters the result (the walk itself is
    not path-scoped, which keeps it to a single subprocess).
    """
    out = _run(
        repo,
        ["log", "--diff-filter=A", "--name-only", "--format=%x00%H%x1f%s"],
    ).stdout.decode("utf-8", errors="replace")
    wanted = set(paths) if paths is not None else None
    result: dict[str, tuple[str, str]] = {}
    current: tuple[str, str] | None = None
    for line in out.splitlines():
        if line.startswith("\0"):
            sha, _, subject = line[1:].partition("\x1f")
            current = (sha, subject)
            continue
        rel = line.strip()
        if not rel or current is None or rel in result:
            continue
        if wanted is not None and rel not in wanted:
            continue
        result[rel] = current
    return result


GOVERNED_ANY_SUBJECT = re.compile(
    r"^content\(locale\): zero-defect shard w\d+:[^:]+:[^:]*:[^:]*:[a-z]{2}:[1-9][0-9]*$"
)


def classify_bulk(
    repo: Path,
    candidates: dict[str, str],
    *,
    baseline_sha: str | None = None,
) -> dict[str, GovernedCommit | str]:
    """Bulk provenance classification for a backfill.

    ``candidates`` maps ``relative_path -> current sha256``.  Returns, per path, a
    :class:`GovernedCommit` when the five rules hold (subject matched against the generic
    governed pattern; the baseline rule is skipped when ``baseline_sha`` is None), else the
    reason string.  Paths with no add commit are reported as ``"no commit provenance"``.
    """
    adds = last_add_commits(repo, candidates)
    result: dict[str, GovernedCommit | str] = {}
    for rel, current_sha in candidates.items():
        found = adds.get(rel)
        if found is None:
            result[rel] = "no commit provenance"
            continue
        sha, subject = found
        if not GOVERNED_ANY_SUBJECT.fullmatch(subject):
            result[rel] = "commit is not governed"
            continue
        try:
            result[rel] = verify_governed_add(
                repo,
                rel,
                subject_pattern=GOVERNED_ANY_SUBJECT,
                baseline_sha=baseline_sha or sha,
                current_sha256=current_sha,
                last_commit=found,
            )
        except GovernedProvenanceError as exc:
            result[rel] = str(exc)
    return result
