"""Versioned, fail-closed campaign manifest support.

The manifest is the authority for campaign scope.  It binds every English
source file to its hash and exact locale output paths so a worker cannot drift
into another product, surface, locale, or repository revision.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
ZERO_DEFECT_POLICY = "zero-defect"


class CampaignManifestError(RuntimeError):
    """Raised when a campaign manifest or its pinned environment is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_files(root: Path, relative_paths: list[str]) -> str:
    """Hash exact file names, sizes, and bytes for an immutable artifact set."""
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = root / relative
        if not path.is_file():
            raise CampaignManifestError(f"fingerprint input missing: {path}")
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def git_sha(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_is_ancestor(repo: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def git_changed_paths(repo: Path, start: str, end: str = "HEAD") -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{start}..{end}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line).as_posix() for line in completed.stdout.splitlines() if line.strip()]


def git_dirty_paths(repo: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    entries = completed.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        paths.append(Path(entry[3:]).as_posix())
        if "R" in status or "C" in status:
            if index < len(entries) and entries[index]:
                paths.append(Path(entries[index]).as_posix())
            index += 1
    return paths


@dataclass(frozen=True)
class CampaignSource:
    site_id: str
    family: str
    platform: str
    source_path: str
    source_sha256: str
    outputs: dict[str, str]
    wave: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignSource:
        return cls(
            site_id=str(data["site_id"]),
            family=str(data["family"]),
            platform=str(data["platform"]),
            source_path=str(data["source_path"]),
            source_sha256=str(data["source_sha256"]),
            outputs={str(k): str(v) for k, v in data["outputs"].items()},
            wave=int(data["wave"]),
        )


@dataclass(frozen=True)
class CampaignManifest:
    schema_version: int
    campaign_id: str
    validation_policy: str
    content_repo: str
    content_repo_sha: str
    translator_repo_sha: str
    config_fingerprint: str
    model_fingerprints: dict[str, str]
    tm_fingerprint: str
    knowledge_fingerprints: dict[str, str]
    target_locales: tuple[str, ...]
    sources: tuple[CampaignSource, ...]
    expected_source_count: int
    expected_output_count: int
    retry_policy: dict[str, Any] = field(default_factory=dict)
    commit_policy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> CampaignManifest:
        manifest_path = Path(path).resolve()
        if not manifest_path.is_file():
            raise CampaignManifestError(f"Campaign manifest not found: {manifest_path}")
        with manifest_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        try:
            manifest = cls(
                schema_version=int(raw["schema_version"]),
                campaign_id=str(raw["campaign_id"]),
                validation_policy=str(raw["validation_policy"]),
                content_repo=str(raw["content_repo"]),
                content_repo_sha=str(raw["content_repo_sha"]),
                translator_repo_sha=str(raw["translator_repo_sha"]),
                config_fingerprint=str(raw["config_fingerprint"]),
                model_fingerprints={str(k): str(v) for k, v in raw["model_fingerprints"].items()},
                tm_fingerprint=str(raw["tm_fingerprint"]),
                knowledge_fingerprints={
                    str(k): str(v) for k, v in raw["knowledge_fingerprints"].items()
                },
                target_locales=tuple(str(item) for item in raw["target_locales"]),
                sources=tuple(CampaignSource.from_dict(item) for item in raw["sources"]),
                expected_source_count=int(raw["expected_source_count"]),
                expected_output_count=int(raw["expected_output_count"]),
                retry_policy=dict(raw.get("retry_policy") or {}),
                commit_policy=dict(raw.get("commit_policy") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CampaignManifestError(f"Invalid campaign manifest: {exc}") from exc
        manifest.validate_schema()
        return manifest

    def validate_schema(self) -> None:
        errors: list[str] = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"schema_version={self.schema_version}, expected {SCHEMA_VERSION}")
        if self.validation_policy != ZERO_DEFECT_POLICY:
            errors.append("campaign validation_policy must be zero-defect")
        if len(set(self.target_locales)) != len(self.target_locales):
            errors.append("target_locales contains duplicates")
        if self.retry_policy.get("primary_attempts") != 3:
            errors.append("zero-defect campaign requires exactly 3 primary attempts")
        if self.retry_policy.get("llm_escalation_attempts") != 2:
            errors.append("zero-defect campaign requires exactly 2 LLM attempts")
        if self.retry_policy.get("llm_model") != "professionalize_llm":
            errors.append("zero-defect campaign LLM escalation must use professionalize_llm")
        if self.commit_policy.get("push") is not False:
            errors.append("zero-defect campaign commit policy must prohibit push")
        max_outputs = self.commit_policy.get("max_outputs_per_commit")
        if not isinstance(max_outputs, int) or not 1 <= max_outputs <= 250:
            errors.append("campaign commit partitions must contain 1..250 outputs")
        if len(self.sources) != self.expected_source_count:
            errors.append(f"source count {len(self.sources)} != {self.expected_source_count}")

        output_paths: set[str] = set()
        job_count = 0
        source_paths: set[str] = set()
        for source in self.sources:
            if source.source_path in source_paths:
                errors.append(f"duplicate source path: {source.source_path}")
            source_paths.add(source.source_path)
            if set(source.outputs) != set(self.target_locales):
                errors.append(f"{source.source_path}: output locales do not match campaign locales")
            for output in source.outputs.values():
                normalized = Path(output)
                if normalized.is_absolute() or ".." in normalized.parts:
                    errors.append(f"unsafe output path: {output}")
                if output in output_paths:
                    errors.append(f"duplicate output path: {output}")
                output_paths.add(output)
                job_count += 1
        if job_count != self.expected_output_count:
            errors.append(f"output count {job_count} != {self.expected_output_count}")
        if errors:
            raise CampaignManifestError("; ".join(errors[:20]))

    def verify_environment(
        self,
        *,
        translator_repo: Path,
        require_clean: bool = True,
        allow_existing_accepted: set[str] | None = None,
    ) -> None:
        """Verify pinned SHAs, clean worktrees, hashes, and output absence."""
        content_repo = Path(self.content_repo).resolve()
        errors: list[str] = []
        if not content_repo.is_dir():
            errors.append(f"content repo missing: {content_repo}")
        else:
            current_content_sha = git_sha(content_repo)
            if current_content_sha != self.content_repo_sha:
                accepted_outputs = {
                    Path(item).as_posix() for item in (allow_existing_accepted or set())
                }
                if not accepted_outputs:
                    errors.append("content repository SHA drift")
                elif not git_is_ancestor(content_repo, self.content_repo_sha, current_content_sha):
                    errors.append("content repository history diverged from campaign pin")
                else:
                    changed = set(
                        git_changed_paths(
                            content_repo,
                            self.content_repo_sha,
                            current_content_sha,
                        )
                    )
                    unexpected_commits = sorted(changed - accepted_outputs)
                    if unexpected_commits:
                        errors.append(
                            "content repository descendants contain "
                            f"{len(unexpected_commits)} non-campaign paths"
                        )
            if require_clean:
                dirty = git_dirty_paths(content_repo)
                allowed_dirty = {
                    Path(item).as_posix() for item in (allow_existing_accepted or set())
                }
                unexpected_dirty = [
                    item for item in dirty if Path(item).as_posix() not in allowed_dirty
                ]
                if unexpected_dirty:
                    errors.append(
                        f"content repository is dirty ({len(unexpected_dirty)} unexpected paths)"
                    )

        translator_repo = translator_repo.resolve()
        if git_sha(translator_repo) != self.translator_repo_sha:
            errors.append("translator repository SHA drift")
        if require_clean:
            dirty = git_dirty_paths(translator_repo)
            if dirty:
                errors.append(f"translator repository is dirty ({len(dirty)} paths)")
        registry_path = translator_repo / "config/model_registry.yaml"
        expected_registry = self.model_fingerprints.get("model_registry")
        if (
            not expected_registry
            or not registry_path.is_file()
            or sha256_file(registry_path) != expected_registry
        ):
            errors.append("model registry fingerprint drift")
        # The baseline TM is pinned before the first accepted job. Campaign
        # acceptance writes mutate the same physical stores; resumed lookups
        # remain isolated by the campaign/config/source namespace.
        if not allow_existing_accepted:
            tm_paths = [
                "data/tm/l2.lmdb/data.mdb",
                "data/tm/l3_faiss/index.faiss",
                "data/tm/l3_faiss/metadata.pkl",
                "data/tm/l3_faiss/config.json",
            ]
            try:
                if fingerprint_files(translator_repo, tm_paths) != self.tm_fingerprint:
                    errors.append("translation memory fingerprint drift")
            except CampaignManifestError as exc:
                errors.append(str(exc))

        accepted = allow_existing_accepted or set()
        for relative, expected_hash in self.knowledge_fingerprints.items():
            knowledge_path = content_repo / relative
            if not knowledge_path.is_file():
                errors.append(f"knowledge artifact missing: {relative}")
            elif sha256_file(knowledge_path) != expected_hash:
                errors.append(f"knowledge fingerprint drift: {relative}")
        for source in self.sources:
            source_path = content_repo / source.source_path
            if not source_path.is_file():
                errors.append(f"source missing: {source.source_path}")
                continue
            if sha256_file(source_path) != source.source_sha256:
                errors.append(f"source hash drift: {source.source_path}")
            for output in source.outputs.values():
                if output not in accepted and (content_repo / output).exists():
                    errors.append(f"unexpected existing output: {output}")
        if errors:
            raise CampaignManifestError("; ".join(errors[:20]))

    def jobs(self, *, resume_receipts: set[str] | None = None):
        completed = resume_receipts or set()
        for source in sorted(
            self.sources,
            key=lambda item: (
                item.wave,
                item.site_id,
                item.family,
                item.platform,
                item.source_path,
            ),
        ):
            for locale in self.target_locales:
                output = source.outputs[locale]
                if output not in completed:
                    yield source, locale, output

    def shards(
        self,
        *,
        resume_receipts: set[str] | None = None,
        max_outputs: int = 250,
    ):
        """Yield deterministic surface/product/locale shards of at most 250 jobs."""
        if max_outputs < 1 or max_outputs > 250:
            raise CampaignManifestError("campaign shards must contain 1..250 outputs")
        completed = resume_receipts or set()
        grouped: dict[
            tuple[int, str, str, str, str],
            list[tuple[CampaignSource, str, str]],
        ] = {}
        for source in self.sources:
            for locale in self.target_locales:
                output = source.outputs[locale]
                if output in completed:
                    continue
                key = (
                    source.wave,
                    source.site_id,
                    source.family,
                    source.platform,
                    locale,
                )
                grouped.setdefault(key, []).append((source, locale, output))
        for key in sorted(grouped):
            jobs = sorted(grouped[key], key=lambda item: item[0].source_path)
            for offset in range(0, len(jobs), max_outputs):
                part = offset // max_outputs + 1
                yield {
                    "shard_id": (f"w{key[0]}:{key[1]}:{key[2]}:{key[3]}:{key[4]}:{part}"),
                    "wave": key[0],
                    "site_id": key[1],
                    "family": key[2],
                    "platform": key[3],
                    "locale": key[4],
                    "part": part,
                    "jobs": jobs[offset : offset + max_outputs],
                }

    def to_summary(self) -> dict[str, Any]:
        per_surface: dict[str, int] = {}
        for source in self.sources:
            per_surface[source.site_id] = per_surface.get(source.site_id, 0) + 1
        return {
            "campaign_id": self.campaign_id,
            "validation_policy": self.validation_policy,
            "source_count": len(self.sources),
            "output_count": self.expected_output_count,
            "locale_count": len(self.target_locales),
            "sources_by_surface": per_surface,
        }


def receipt_fingerprint(receipt: dict[str, Any]) -> str:
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
