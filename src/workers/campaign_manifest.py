"""Versioned, fail-closed campaign manifest support.

The manifest is the authority for campaign scope.  It binds every English
source file to its hash and exact locale output paths so a worker cannot drift
into another product, surface, locale, or repository revision.
"""

from __future__ import annotations

import hashlib
import os
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
ZERO_DEFECT_POLICY = "zero-defect"
#: TC-APT-032: how verify_environment treats a dirty content repository.
#:  frozen_baseline -- the historical whole-tree frozen dirty baseline (single-writer repos)
#:  campaign_paths  -- only the manifest's own sources/outputs matter (shared repos; mission default)
DIRTY_SCOPES = ("frozen_baseline", "campaign_paths")
DEFAULT_DIRTY_SCOPE = "frozen_baseline"
#: TM artifacts bound into a manifest by default (a manifest may declare its own list).
DEFAULT_TM_FINGERPRINT_INPUTS: tuple[str, ...] = (
    "data/tm/l2.lmdb/data.mdb",
    "data/tm/l3_faiss/index.faiss",
    "data/tm/l3_faiss/metadata.pkl",
    "data/tm/l3_faiss/config.json",
)


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


def dirty_path_fingerprints(
    repo: Path,
    *,
    exclude_paths: set[str] | None = None,
) -> dict[str, str | None]:
    """Return a deterministic, content-addressed snapshot of dirty paths.

    A direct-destination campaign may coexist with unrelated user changes.  It
    must preserve those changes exactly rather than treating a dirty worktree as
    permission to modify arbitrary paths.  ``None`` denotes a tracked deletion.
    """
    excluded = {Path(item).as_posix() for item in (exclude_paths or set())}
    snapshot: dict[str, str | None] = {}
    for relative in git_dirty_paths(repo):
        normalized = Path(relative).as_posix()
        if normalized in excluded:
            continue
        path = repo / normalized
        snapshot[normalized] = sha256_file(path) if path.is_file() else None
    return dict(sorted(snapshot.items()))


def dirty_snapshot_fingerprint(paths: dict[str, str | None]) -> str:
    """Fingerprint a frozen dirty baseline without storing candidate bytes."""
    encoded = json.dumps(paths, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CampaignSource:
    site_id: str
    family: str
    platform: str
    source_path: str
    source_sha256: str
    outputs: dict[str, str]
    wave: int
    #: TC-APT-031: locale -> {expected_sha256, reason_code}. A declared cell may overwrite the
    #: existing target ONLY while its current bytes still hash to expected_sha256.
    replace_existing: dict[str, dict[str, str]] = field(default_factory=dict)

    def replacement_for(self, locale: str) -> dict[str, str] | None:
        return self.replace_existing.get(locale)

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
            replace_existing={
                str(locale): {str(k): str(v) for k, v in (spec or {}).items()}
                for locale, spec in (data.get("replace_existing") or {}).items()
            },
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
    execution_policy: dict[str, Any] = field(default_factory=dict)
    destination_baseline: dict[str, Any] = field(default_factory=dict)
    tm_fingerprint_inputs: tuple[str, ...] = DEFAULT_TM_FINGERPRINT_INPUTS

    @property
    def dirty_scope(self) -> str:
        return str(self.execution_policy.get("dirty_scope", DEFAULT_DIRTY_SCOPE))

    def declared_replacements(self) -> dict[str, dict[str, str]]:
        """output path -> {expected_sha256, reason_code, source_path, locale} for every declared cell."""
        out: dict[str, dict[str, str]] = {}
        for source in self.sources:
            for locale, spec in source.replace_existing.items():
                out[source.outputs[locale]] = {
                    **spec,
                    "source_path": source.source_path,
                    "locale": locale,
                }
        return out

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
                execution_policy=dict(raw.get("execution_policy") or {}),
                destination_baseline=dict(raw.get("destination_baseline") or {}),
                tm_fingerprint_inputs=tuple(
                    str(item)
                    for item in (raw.get("tm_fingerprint_inputs") or DEFAULT_TM_FINGERPRINT_INPUTS)
                ),
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
        # TC-APT-039 (plan revision 8, §6.1): the primary/escalation pair may run in
        # either direction -- m2m100 primary with professionalize_llm escalation (the
        # original design), or professionalize_llm primary with m2m100 escalation (for
        # the 22 languages TC-APT-006 measured the LLM better in). Both models must
        # still be present, in opposite roles; a manifest naming the same model for
        # both, or a model outside this pair, is never valid.
        _primary = self.retry_policy.get("primary_model")
        _escalation = self.retry_policy.get("llm_model")
        _valid_pairs = {
            ("m2m100_418m", "professionalize_llm"),
            ("m2m100_1.2b", "professionalize_llm"),
            ("professionalize_llm", "m2m100_418m"),
        }
        _professionalize_only = bool(self.retry_policy.get("professionalize_only", False))
        if _professionalize_only:
            if _primary != "professionalize_llm" or _escalation != "professionalize_llm":
                errors.append("professionalize_only requires Professionalize as both primary and retry target")
        elif (_primary, _escalation) not in _valid_pairs:
            errors.append(
                "zero-defect campaign model pair must be M2M100 primary with "
                "professionalize_llm escalation (or the approved inverse pair), got "
                f"primary_model={_primary!r} llm_model={_escalation!r}"
            )
        if self.retry_policy.get("primary_attempts") != 3:
            errors.append("zero-defect campaign requires exactly 3 primary attempts")
        _escalation_mode = self.retry_policy.get("llm_escalation_mode", "immediate")
        _llm_attempts = self.retry_policy.get("llm_escalation_attempts")
        if _professionalize_only:
            if _escalation_mode != "professionalize_only" or _llm_attempts != 0:
                errors.append("professionalize_only requires professionalize_only mode and zero escalation attempts")
        elif _escalation_mode == "immediate" and _llm_attempts != 2:
            errors.append("immediate LLM escalation requires exactly 2 LLM attempts")
        elif _escalation_mode == "deferred":
            if _llm_attempts != 0:
                errors.append("deferred LLM escalation requires zero in-run LLM attempts")
            if _primary not in {"m2m100_418m", "m2m100_1.2b"} or _escalation != "professionalize_llm":
                errors.append("deferred LLM escalation requires an M2M100 primary and Professionalize queue target")
        elif _escalation_mode not in {"immediate", "deferred"}:
            errors.append("llm_escalation_mode must be immediate or deferred")
        if self.commit_policy.get("push") is not False:
            errors.append("zero-defect campaign commit policy must prohibit push")
        if not isinstance(self.commit_policy.get("enabled", True), bool):
            errors.append("campaign commit policy enabled must be boolean")
        max_outputs = self.commit_policy.get("max_outputs_per_commit")
        if not isinstance(max_outputs, int) or not 1 <= max_outputs <= 250:
            errors.append("campaign commit partitions must contain 1..250 outputs")
        # TC-APT-046/TC-APT-064: ceiling raised 4 -> 64 on TC-APT-064's sustained-load
        # evidence (data/benchmark_corpus/results/professionalize_llm_calibration_tc064_
        # sustained_20260906.json): 16/32/48/64 concurrent held 450s each, 3611 calls
        # total, 0 errors, 0 rate-limited at every level (sustained_safe_ceiling=64 is a
        # floor, not a measured max -- the probe did not find a ceiling within range).
        max_parallel_jobs = self.execution_policy.get("max_parallel_jobs", 1)
        if not isinstance(max_parallel_jobs, int) or not 1 <= max_parallel_jobs <= 64:
            errors.append("campaign execution max_parallel_jobs must be 1..64")
        if (
            max_parallel_jobs > 1
            and self.execution_policy.get("model_sharing") != "single_shared_instance"
        ):
            errors.append(
                "parallel campaign execution requires model_sharing=single_shared_instance"
            )
        if len(self.sources) != self.expected_source_count:
            errors.append(f"source count {len(self.sources)} != {self.expected_source_count}")
        if self.dirty_scope not in DIRTY_SCOPES:
            errors.append(f"execution_policy.dirty_scope must be one of {DIRTY_SCOPES}")
        if not self.tm_fingerprint_inputs or not all(
            isinstance(p, str) and p for p in self.tm_fingerprint_inputs
        ):
            errors.append("tm_fingerprint_inputs must be a non-empty list of paths")
        for source in self.sources:
            for locale, spec in source.replace_existing.items():
                if locale not in source.outputs:
                    errors.append(
                        f"{source.source_path}: replace_existing locale {locale!r} is not an output"
                    )
                    continue
                sha = str(spec.get("expected_sha256", ""))
                if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                    errors.append(
                        f"{source.source_path}[{locale}]: replace_existing.expected_sha256 is not a sha256"
                    )
                if not str(spec.get("reason_code", "")).strip():
                    errors.append(
                        f"{source.source_path}[{locale}]: replace_existing.reason_code is required"
                    )

        if self.destination_baseline:
            paths = self.destination_baseline.get("paths")
            fingerprint = self.destination_baseline.get("fingerprint")
            if not isinstance(paths, dict) or not all(
                isinstance(key, str) and (value is None or isinstance(value, str))
                for key, value in paths.items()
            ):
                errors.append("destination baseline paths must be a path/hash map")
            elif fingerprint != dirty_snapshot_fingerprint(paths):
                errors.append("destination baseline fingerprint mismatch")

        output_paths: set[str] = set()
        job_count = 0
        source_paths: set[str] = set()
        for source in self.sources:
            if source.source_path in source_paths:
                errors.append(f"duplicate source path: {source.source_path}")
            source_paths.add(source.source_path)
            source_locales = set(source.outputs)
            campaign_locales = set(self.target_locales)
            missing_only = self.execution_policy.get("output_selection") == "missing_only"
            if not source_locales:
                errors.append(f"{source.source_path}: source has no output locales")
            elif missing_only and not source_locales.issubset(campaign_locales):
                errors.append(
                    f"{source.source_path}: output locales are outside campaign locales"
                )
            elif not missing_only and source_locales != campaign_locales:
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
        scope_sources: set[str] | None = None,
        scope_outputs: set[str] | None = None,
        allow_campaign_tm_drift: bool = False,
    ) -> None:
        """Verify pinned SHAs, clean worktrees, hashes, and output absence.

        ``scope_sources``/``scope_outputs`` allow a governed parallel child to
        verify only the immutable shard set assigned to that child. Repository
        and configuration pins remain global. This prevents every child from
        walking the entire portfolio while retaining source/output hash gates
        for every path it can read or write.
        """
        content_repo = Path(self.content_repo).resolve()
        errors: list[str] = []
        if not content_repo.is_dir():
            errors.append(f"content repo missing: {content_repo}")
        else:
            current_content_sha = git_sha(content_repo)
            campaign_scoped = self.dirty_scope == "campaign_paths"
            manifest_outputs = {o for s in self.sources for o in s.outputs.values()}
            manifest_sources = {s.source_path for s in self.sources}
            requested_outputs = (
                {Path(item).as_posix() for item in scope_outputs}
                if scope_outputs is not None
                else manifest_outputs
            )
            requested_sources = (
                {Path(item).as_posix() for item in scope_sources}
                if scope_sources is not None
                else manifest_sources
            )
            unknown_outputs = sorted(requested_outputs - manifest_outputs)
            unknown_sources = sorted(requested_sources - manifest_sources)
            if unknown_outputs:
                errors.append(f"verification scope has unknown outputs: {unknown_outputs[:5]}")
            if unknown_sources:
                errors.append(f"verification scope has unknown sources: {unknown_sources[:5]}")
            all_outputs = requested_outputs & manifest_outputs
            all_sources = requested_sources & manifest_sources
            declared = {
                path: spec
                for path, spec in self.declared_replacements().items()
                if path in all_outputs
            }
            if current_content_sha != self.content_repo_sha and campaign_scoped:
                # TC-APT-032: other sessions commit continuously in a shared repo. HEAD may move
                # as long as the pin is an ancestor and nothing the campaign reads/writes changed
                # outside receipts.
                if not git_is_ancestor(content_repo, self.content_repo_sha, current_content_sha):
                    errors.append("content repository history diverged from campaign pin")
                else:
                    changed = set(
                        git_changed_paths(content_repo, self.content_repo_sha, current_content_sha)
                    )
                    accepted_set = {Path(i).as_posix() for i in (allow_existing_accepted or set())}
                    changed_sources = sorted(changed & all_sources)
                    if changed_sources:
                        errors.append(f"campaign source changed since pin: {changed_sources[:5]}")
                    changed_outputs = sorted((changed & all_outputs) - accepted_set - set(declared))
                    if changed_outputs and os.environ.get("CAMPAIGN_ALLOW_UNRECEIPTED_OUTPUTS") != "1":
                        errors.append(
                            f"campaign output changed outside receipts: {changed_outputs[:5]}"
                        )
            elif current_content_sha != self.content_repo_sha:
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
            if require_clean and campaign_scoped:
                # TC-APT-032: only the campaign's own paths matter. Unrelated dirty paths are
                # ignored, never staged, never committed (session-ledger scoping on the commit side).
                dirty = {Path(item).as_posix() for item in git_dirty_paths(content_repo)}
                accepted_set = {Path(i).as_posix() for i in (allow_existing_accepted or set())}
                dirty_sources = sorted(dirty & all_sources)
                if dirty_sources:
                    errors.append(
                        f"campaign source is dirty (translating a moving source is unsafe): {dirty_sources[:5]}"
                    )
                # TC-APT-075: mirror the SHA-drift check above (line ~393), which already
                # excludes `declared` -- a declared replacement's expected_sha256 is the
                # CURRENT on-disk hash re-read at manifest-build time (build_campaign_manifest.py
                # ::_declared_replacements), so the target being locally dirty relative to git
                # HEAD is expected, not a hazard: it is either this campaign's own prior
                # (possibly review-rejected, uncommitted) output for the exact same cell, or
                # any other uncommitted edit already vetted by that hash. The real safety net is
                # downstream and per-job: _run_campaign_job raises "declared replacement
                # pre-hash drift" the instant a declared target's bytes no longer match
                # expected_sha256, catching genuine concurrent modification between
                # manifest-build and execution. Before this fix, a review-rejected page could
                # never be regenerated in the live tree: its own prior (uncommitted) draft
                # tripped this check on every relaunch, and neither a fresh campaign_id nor
                # --resume could route around it (a fresh id can't attribute pre-existing
                # untracked output; resume re-gates existing bytes instead of re-translating).
                dirty_candidates = sorted((dirty & all_outputs) - accepted_set - set(declared))
                if dirty_candidates and os.environ.get("CAMPAIGN_ALLOW_UNRECEIPTED_OUTPUTS") != "1":
                    errors.append(f"unreceipted campaign output is dirty: {dirty_candidates[:5]}")
            elif require_clean:
                dirty = git_dirty_paths(content_repo)
                allowed_dirty = {
                    Path(item).as_posix() for item in (allow_existing_accepted or set())
                }
                if self.destination_baseline:
                    expected_dirty = {
                        Path(key).as_posix(): value
                        for key, value in self.destination_baseline["paths"].items()
                    }
                    actual_dirty = dirty_path_fingerprints(
                        content_repo,
                        exclude_paths=allowed_dirty,
                    )
                    if actual_dirty != expected_dirty:
                        errors.append(
                            "content repository frozen dirty baseline drift "
                            f"(expected={len(expected_dirty)}, actual={len(actual_dirty)})"
                        )
                else:
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
            if self.dirty_scope == "campaign_paths":
                # TC-APT-032 companion fix (found via the vsprint107 validation sprint's real
                # concurrent-launcher test, 2026-09-10): this mission runs as a multi-session
                # fleet against ONE shared hugo-translator checkout. Sibling campaigns write to
                # the shared data/campaigns/ ledger area (heal_queue.jsonl, claims.jsonl,
                # work_ledger.sqlite3 + _events.jsonl, per-campaign summary/receipt directories,
                # manifests/) at any moment while THIS campaign is trying to (re)launch --
                # that is expected concurrent bookkeeping, not a hazard to this campaign's own
                # translation work. Unlike the content-repo side just above (~line 447), which
                # already scopes "campaign_paths" to ignore paths outside its own
                # sources/outputs, this translator-repo check never got the same treatment and
                # unconditionally failed on ANY dirty path fleet-wide -- confirmed live: a
                # second launcher's verify_environment call was refused with "translator
                # repository is dirty (1 paths)" solely because a SIBLING campaign had an
                # in-flight, uncommitted append to data/campaigns/heal_queue.jsonl. Code/config
                # dirtiness elsewhere in the tree still fails the check, as before.
                #
                # .supervisor/state/ extension (2026-09-12): the exact same race, one directory
                # over. Every session in this fleet writes its own mission-loop bookkeeping
                # (taskcard_status.json, active_detached_runs, etc.) to .supervisor/state/
                # continuously and independently of any campaign's own translation work --
                # confirmed live: a single-cell heal retrigger died 3x in a row on "translator
                # repository is dirty (1 paths)" purely because a sibling session's concurrent
                # edit to taskcard_status.json landed in the narrow window between manifest
                # build and launch, well after the batch campaign whose ledger churn this
                # exemption was originally written for had already exited. Same rationale as
                # data/campaigns/ above: generated runtime state, never a translation-safety
                # hazard, never staged or committed by this check.
                # `build_campaign_manifest.py` regenerates this inventory as a
                # report-only discovery artifact. It is deliberately absent
                # from CONFIG_FINGERPRINT_SHARED and no runtime component reads
                # it, so a sibling inventory refresh cannot invalidate an
                # already-bound campaign execution revision.
                _exempt_prefixes = (
                    "data/campaigns/",
                    ".supervisor/state/",
                    "config/inventory/",
                )
                dirty = [
                    item
                    for item in dirty
                    if not Path(item).as_posix().startswith(_exempt_prefixes)
                ]
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
        if not allow_existing_accepted and not allow_campaign_tm_drift:
            tm_paths = list(self.tm_fingerprint_inputs)
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
            if source.source_path not in all_sources:
                continue
            source_path = content_repo / source.source_path
            if not source_path.is_file():
                errors.append(f"source missing: {source.source_path}")
                continue
            if sha256_file(source_path) != source.source_sha256:
                errors.append(f"source hash drift: {source.source_path}")
            for locale, output in source.outputs.items():
                if output not in all_outputs:
                    continue
                if output in accepted or not (content_repo / output).exists():
                    continue
                spec = source.replacement_for(locale)
                if spec is None:
                    # During a live multi-worker wave another worker may have
                    # atomically materialized this output before its receipt
                    # journal is merged. The controller will reconcile that
                    # journal at the wave boundary; do not abort every peer
                    # worker on this transient state.
                    if os.environ.get("CAMPAIGN_ALLOW_UNRECEIPTED_OUTPUTS") == "1":
                        continue
                    errors.append(f"unexpected existing output: {output}")
                elif sha256_file(content_repo / output) != spec.get("expected_sha256"):
                    errors.append(
                        f"declared replacement drifted (current bytes != expected_sha256): {output}"
                    )
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
                output = source.outputs.get(locale)
                if output is None:
                    continue
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
                output = source.outputs.get(locale)
                if output is None:
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
                # Chunk immutable manifest jobs before removing completed cells.
                # Otherwise accepting part 1 renumbers part 2 to part 1, and a
                # durable wave cursor silently skips untranslated outputs.
                pending_jobs = [job for job in jobs[offset : offset + max_outputs]
                                if job[2] not in completed]
                if not pending_jobs:
                    continue
                yield {
                    "shard_id": (f"w{key[0]}:{key[1]}:{key[2]}:{key[3]}:{key[4]}:{part}"),
                    "wave": key[0],
                    "site_id": key[1],
                    "family": key[2],
                    "platform": key[3],
                    "locale": key[4],
                    "part": part,
                    "jobs": pending_jobs,
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
            "dirty_scope": self.dirty_scope,
            "replace_existing_count": sum(len(s.replace_existing) for s in self.sources),
        }


def receipt_fingerprint(receipt: dict[str, Any]) -> str:
    # JSON object keys are strings on disk. Canonicalize in memory first so
    # gate_results={1: ..., 2: ...} and the reloaded {"1": ..., "2": ...}
    # produce the same ordering and fingerprint across campaign restarts.
    canonical = json.loads(json.dumps(receipt, ensure_ascii=False))
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def legacy_integer_gate_receipt_fingerprint(receipt: dict[str, Any]) -> str:
    """Reproduce the pre-canonicalization signature for narrow migration."""
    legacy = json.loads(json.dumps(receipt, ensure_ascii=False))
    gates = legacy.get("gate_results")
    if not isinstance(gates, dict) or not all(str(key).isdigit() for key in gates):
        return ""
    legacy["gate_results"] = {int(key): value for key, value in gates.items()}
    encoded = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
