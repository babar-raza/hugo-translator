"""Immutable policy artifact for governed campaign throughput promotion.

The campaign must never obtain higher Professionalize concurrency merely because a
shared global configuration changed.  A release artifact binds the permitted phase
to one campaign, one manifest byte stream, and one runtime revision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ThroughputReleaseError(ValueError):
    """A release artifact is absent, malformed, or does not bind this run."""


@dataclass(frozen=True)
class ThroughputRelease:
    campaign_id: str
    phase: str
    runtime_sha: str
    manifest_sha256: str
    processes: int
    max_parallel_jobs: int
    fleet_llm_slots: int
    force_serialize: bool
    approved: bool
    evidence_path: str


_PHASES: dict[str, dict[str, int | bool]] = {
    "baseline": {"processes": 4, "max_parallel_jobs": 1, "fleet_llm_slots": 4, "force_serialize": True},
    "canary16": {"processes": 4, "max_parallel_jobs": 4, "fleet_llm_slots": 16, "force_serialize": False},
    "soak32": {"processes": 4, "max_parallel_jobs": 8, "fleet_llm_slots": 32, "force_serialize": False},
}


def manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release(path: Path) -> ThroughputRelease:
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThroughputReleaseError(f"invalid throughput release artifact: {path}") from exc
    phase = str(raw.get("phase") or "")
    if phase not in _PHASES:
        raise ThroughputReleaseError(f"unsupported throughput phase: {phase!r}")
    expected = _PHASES[phase]
    try:
        release = ThroughputRelease(
            campaign_id=str(raw["campaign_id"]), phase=phase,
            runtime_sha=str(raw["runtime_sha"]), manifest_sha256=str(raw["manifest_sha256"]),
            processes=int(raw["processes"]), max_parallel_jobs=int(raw["max_parallel_jobs"]),
            fleet_llm_slots=int(raw["fleet_llm_slots"]), force_serialize=bool(raw["force_serialize"]),
            approved=bool(raw.get("approved", False)), evidence_path=str(raw.get("evidence_path") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ThroughputReleaseError("release artifact has invalid required fields") from exc
    if any(getattr(release, key) != value for key, value in expected.items()):
        raise ThroughputReleaseError(f"release phase {phase} does not match its immutable limits")
    if len(release.runtime_sha) != 40 or len(release.manifest_sha256) != 64:
        raise ThroughputReleaseError("release artifact contains invalid revision hashes")
    if phase != "baseline" and (not release.approved or not release.evidence_path):
        raise ThroughputReleaseError(f"{phase} requires an approved evidence-backed release artifact")
    return release


def verify_release(path: Path, *, campaign_id: str, runtime_sha: str, manifest_path: Path) -> ThroughputRelease:
    release = load_release(path)
    if release.campaign_id != campaign_id:
        raise ThroughputReleaseError("release artifact campaign_id does not match manifest")
    if release.runtime_sha.lower() != runtime_sha.lower():
        raise ThroughputReleaseError("runtime SHA does not match release artifact")
    if release.manifest_sha256.lower() != manifest_sha256(manifest_path).lower():
        raise ThroughputReleaseError("manifest bytes do not match release artifact")
    return release

