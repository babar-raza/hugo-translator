"""Recover safe legacy translation backlog from a live content repository."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from src.observability.git_commit import GitCommitConfig, GitCommitter


@dataclass
class LegacyRecoveryCandidate:
    path: Path
    site_id: str
    reason: str


@dataclass
class LegacyRecoverySkipped:
    path: str
    reason: str


@dataclass
class LegacyRecoveryCommit:
    site_id: str
    file_count: int
    commit_hash: str | None


@dataclass
class LegacyRecoveryReport:
    repo: str
    accepted: dict[str, list[str]]
    skipped: list[LegacyRecoverySkipped]
    commits: list[LegacyRecoveryCommit]

    def to_json(self) -> str:
        return json.dumps(
            {
                "repo": self.repo,
                "accepted": self.accepted,
                "skipped": [asdict(item) for item in self.skipped],
                "commits": [asdict(item) for item in self.commits],
            },
            indent=2,
            ensure_ascii=False,
        )


def _git_status_entries(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _site_from_relpath(relpath: Path) -> str | None:
    parts = relpath.parts
    if len(parts) >= 2 and parts[0] == "content":
        return parts[1]
    return None


def _is_translation_output(relpath: Path, site_profile) -> tuple[bool, str]:
    if relpath.suffix.lower() != ".md":
        return False, "not markdown"

    output_layout = getattr(site_profile, "output_layout", None)
    per_language_folders = bool(
        output_layout and getattr(output_layout, "per_language_folders", False)
    )
    source_lang = getattr(site_profile, "default_source_lang", "en")
    target_langs = set(getattr(site_profile, "target_langs", []) or [])

    if per_language_folders:
        parts = relpath.parts
        try:
            lang = parts[3]
        except IndexError:
            return False, "missing language folder"
        if lang == source_lang:
            return False, "source-language folder"
        if lang not in target_langs:
            return False, f"unknown language folder: {lang}"
        return True, f"target-language folder: {lang}"

    stem_parts = relpath.stem.rsplit(".", 1)
    if len(stem_parts) != 2:
        return False, "filename has no target language suffix"
    lang = stem_parts[1]
    if lang == source_lang:
        return False, "source-language suffix"
    if lang not in target_langs:
        return False, f"unknown language suffix: {lang}"
    return True, f"target-language suffix: {lang}"


def _expand_status_path(repo: Path, status_path: str) -> Iterable[Path]:
    abs_path = repo / status_path
    if abs_path.is_dir():
        yield from sorted(p for p in abs_path.rglob("*.md") if p.is_file())
        return
    if abs_path.is_file():
        yield abs_path


def recover_legacy_translation_backlog(
    *,
    repo: Path,
    config_service,
    validate_fn: Callable[[Path, Path, str, bool], bool],
    build_message_fn: Callable[[list[Path], str, GitCommitConfig], str],
    site_ids: list[str] | None = None,
    apply: bool = True,
) -> LegacyRecoveryReport:
    """Recover safe pre-manifest translation leftovers.

    The selection is strict:
    - only dirty markdown paths under content/<site>
    - only target-language outputs per site profile
    - only files that pass the structural integrity gate
    """
    candidates: list[LegacyRecoveryCandidate] = []
    skipped: list[LegacyRecoverySkipped] = []
    commits: list[LegacyRecoveryCommit] = []
    seen: set[Path] = set()
    allowed_sites = set(site_ids or [])

    for line in _git_status_entries(repo):
        status_path = line[3:].strip()
        for abs_path in _expand_status_path(repo, status_path):
            if abs_path in seen:
                continue
            seen.add(abs_path)

            try:
                relpath = abs_path.relative_to(repo)
            except ValueError:
                skipped.append(LegacyRecoverySkipped(path=str(abs_path), reason="outside repository"))
                continue

            site_id = _site_from_relpath(relpath)
            if not site_id:
                skipped.append(LegacyRecoverySkipped(path=str(relpath), reason="outside content/<site>"))
                continue
            if allowed_sites and site_id not in allowed_sites:
                continue

            try:
                profile = config_service.get_site_profile(site_id)
            except Exception:
                skipped.append(LegacyRecoverySkipped(path=str(relpath), reason=f"no site profile for {site_id}"))
                continue

            is_output, reason = _is_translation_output(relpath, profile)
            if not is_output:
                skipped.append(LegacyRecoverySkipped(path=str(relpath), reason=reason))
                continue

            candidates.append(LegacyRecoveryCandidate(path=abs_path, site_id=site_id, reason=reason))

    accepted_by_site: dict[str, list[Path]] = defaultdict(list)
    for item in candidates:
        profile = config_service.get_site_profile(item.site_id)
        output_layout = getattr(profile, "output_layout", None)
        per_language_folders = bool(
            output_layout and getattr(output_layout, "per_language_folders", False)
        )
        source_lang = getattr(profile, "default_source_lang", "en")

        if validate_fn(item.path, repo, source_lang, per_language_folders):
            accepted_by_site[item.site_id].append(item.path)
        else:
            skipped.append(
                LegacyRecoverySkipped(
                    path=str(item.path.relative_to(repo)),
                    reason="failed structural gate",
                )
            )

    if apply:
        for site_id, files in sorted(accepted_by_site.items()):
            config = GitCommitConfig(auto_push=False)
            committer = GitCommitter(config)
            staged = committer._stage_files(files, repo)
            commit_hash = None
            if staged > 0:
                message = build_message_fn(files, site_id, config)
                commit_hash = committer._create_commit(message, repo, files)
            commits.append(
                LegacyRecoveryCommit(site_id=site_id, file_count=len(files), commit_hash=commit_hash)
            )

    return LegacyRecoveryReport(
        repo=str(repo),
        accepted={
            site_id: [str(path.relative_to(repo)) for path in paths]
            for site_id, paths in sorted(accepted_by_site.items())
        },
        skipped=skipped,
        commits=commits,
    )
