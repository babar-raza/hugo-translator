"""
Persistent ownership manifests for translation commit recovery.

Each manifest records the exact files a translation run intends to commit.
This lets the normal worker commit only its own files and lets orphan recovery
retry only previously owned translation outputs after a failed commit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(run_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id).strip("_")
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:12]
    return f"{slug[:80] or 'run'}_{digest}.json"


def _hash_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass
class CommitManifestFile:
    path: str
    sha256: Optional[str] = None


@dataclass
class CommitManifest:
    schema_version: str
    run_id: str
    site_id: str
    target_langs: List[str]
    status: str
    files: List[CommitManifestFile] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    committed_at: Optional[str] = None
    commit_hash: Optional[str] = None
    last_error: Optional[str] = None


class CommitManifestStore:
    def __init__(self, git_root: Path):
        self.git_root = git_root
        self.root = git_root / ".git" / "hugo-translator" / "commit-manifests"

    def path_for_run(self, run_id: str) -> Path:
        return self.root / _safe_name(run_id)

    def write_manifest(
        self,
        run_id: str,
        site_id: str,
        target_langs: List[str],
        files: List[Path],
        status: str,
        *,
        last_error: Optional[str] = None,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = CommitManifest(
            schema_version="1.0",
            run_id=run_id,
            site_id=site_id,
            target_langs=list(target_langs),
            status=status,
            files=[
                CommitManifestFile(
                    path=str(path.relative_to(self.git_root)).replace("\\", "/"),
                    sha256=_hash_file(path),
                )
                for path in files
                if path.exists()
            ],
            last_error=last_error,
        )
        path = self.path_for_run(run_id)
        path.write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def load_manifest(self, path: Path) -> CommitManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = [CommitManifestFile(**item) for item in data.get("files", [])]
        return CommitManifest(
            schema_version=data.get("schema_version", "1.0"),
            run_id=data["run_id"],
            site_id=data["site_id"],
            target_langs=list(data.get("target_langs", [])),
            status=data["status"],
            files=files,
            created_at=data.get("created_at", _utc_now()),
            updated_at=data.get("updated_at", _utc_now()),
            committed_at=data.get("committed_at"),
            commit_hash=data.get("commit_hash"),
            last_error=data.get("last_error"),
        )

    def update_status(
        self,
        path: Path,
        *,
        status: str,
        commit_hash: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> CommitManifest:
        manifest = self.load_manifest(path)
        manifest.status = status
        manifest.updated_at = _utc_now()
        manifest.last_error = last_error
        if commit_hash:
            manifest.commit_hash = commit_hash
            manifest.committed_at = _utc_now()
        path.write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return manifest

    def list_manifests(self) -> List[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.glob("*.json"))
