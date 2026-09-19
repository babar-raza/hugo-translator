"""Remove currently dirty content sources from an already-built manifest.

Used when a shared aspose.org checkout has an unrelated producer holding a
source file. The source remains in the next discovery run; this command only
creates a safe deferred-work manifest and never edits content.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from src.workers.campaign_manifest import git_dirty_paths, git_sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--content-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    dirty = {Path(item).as_posix() for item in git_dirty_paths(args.content_repo)}
    deferred = sorted(
        str(item["source_path"]) for item in data.get("sources", [])
        if str(item["source_path"]) in dirty
    )
    data["sources"] = [item for item in data.get("sources", []) if str(item["source_path"]) not in dirty]
    data["deferred_dirty_sources"] = deferred
    data["expected_source_count"] = len(data["sources"])
    data["expected_output_count"] = sum(len(item.get("outputs", {})) for item in data["sources"])
    data["sites"] = sorted({str(item["site_id"]) for item in data["sources"]})
    data["content_repo_sha"] = git_sha(args.content_repo)
    data["translator_repo_sha"] = git_sha(Path.cwd())
    data["manifest_sha256_before_filter"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    args.output.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"deferred_dirty_sources={len(deferred)} sources={data['expected_source_count']} outputs={data['expected_output_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
