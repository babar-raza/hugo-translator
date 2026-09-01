"""Build the pinned Aspose FOSS 25-locale campaign manifest.

The builder refuses dirty repositories because a manifest generated from
uncommitted state cannot provide an immutable translation baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import yaml

from src.utils.atomic_write import atomic_write
from src.workers.campaign_manifest import (
    fingerprint_files,
    git_dirty_paths,
    git_sha,
    sha256_file,
)


TARGET_LOCALES = (
    "ar", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "hu",
    "id", "it", "ja", "ko", "nl", "pl", "pt", "ro", "ru", "sv",
    "th", "tr", "uk", "vi", "zh",
)
PRODUCTS = (("words", "net"), ("html", "python"), ("cells", "rust"))
FOLDER_SURFACES = (
    ("products.aspose.org", 1),
    ("kb.aspose.org", 1),
    ("docs.aspose.org", 2),
    ("reference.aspose.org", 0),
)
EXPECTED_SOURCE_COUNT = 1213
EXPECTED_OUTPUT_COUNT = 30325
_LOCALE_FILE_RE = re.compile(r"\.[a-z]{2}\.md$")


def _config_fingerprint(translator_repo: Path) -> str:
    digest = hashlib.sha256()
    paths = [translator_repo / "config/global.yaml"]
    paths.extend(
        translator_repo / "config/site_profiles" / f"{site}.yaml"
        for site, _ in FOLDER_SURFACES
    )
    paths.append(
        translator_repo / "config/site_profiles/blog.aspose.org.yaml"
    )
    for path in paths:
        digest.update(path.relative_to(translator_repo).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _folder_sources(content_repo: Path):
    for site_id, default_wave in FOLDER_SURFACES:
        for family, platform in PRODUCTS:
            root = (
                content_repo
                / "content"
                / site_id
                / "en"
                / family
                / platform
            )
            for source in sorted(root.rglob("*.md")):
                relative_tail = source.relative_to(root)
                source_rel = source.relative_to(content_repo).as_posix()
                outputs = {
                    locale: (
                        Path("content")
                        / site_id
                        / locale
                        / family
                        / platform
                        / relative_tail
                    ).as_posix()
                    for locale in TARGET_LOCALES
                }
                if site_id == "reference.aspose.org":
                    wave = {"cells": 3, "html": 4, "words": 5}[family]
                else:
                    wave = default_wave
                yield {
                    "site_id": site_id,
                    "family": family,
                    "platform": platform,
                    "source_path": source_rel,
                    "source_sha256": sha256_file(source),
                    "outputs": outputs,
                    "wave": wave,
                }


def _blog_sources(content_repo: Path):
    site_id = "blog.aspose.org"
    for family, platform in PRODUCTS:
        root = content_repo / "content" / site_id / family / platform
        for source in sorted(root.rglob("*.md")):
            if _LOCALE_FILE_RE.search(source.name):
                continue
            source_rel = source.relative_to(content_repo).as_posix()
            outputs = {
                locale: source.with_name(
                    f"{source.stem}.{locale}{source.suffix}"
                ).relative_to(content_repo).as_posix()
                for locale in TARGET_LOCALES
            }
            yield {
                "site_id": site_id,
                "family": family,
                "platform": platform,
                "source_path": source_rel,
                "source_sha256": sha256_file(source),
                "outputs": outputs,
                "wave": 1,
            }


def build_manifest(
    *,
    content_repo: Path,
    translator_repo: Path,
    campaign_id: str,
) -> dict:
    content_dirty = git_dirty_paths(content_repo)
    translator_dirty = git_dirty_paths(translator_repo)
    if content_dirty or translator_dirty:
        raise RuntimeError(
            "Immutable manifest requires clean repositories: "
            f"content_dirty={len(content_dirty)}, translator_dirty={len(translator_dirty)}"
        )

    sources = [*_folder_sources(content_repo), *_blog_sources(content_repo)]
    output_count = sum(len(item["outputs"]) for item in sources)
    if len(sources) != EXPECTED_SOURCE_COUNT or output_count != EXPECTED_OUTPUT_COUNT:
        raise RuntimeError(
            "Campaign denominator drift: "
            f"sources={len(sources)}/{EXPECTED_SOURCE_COUNT}, "
            f"outputs={output_count}/{EXPECTED_OUTPUT_COUNT}"
        )

    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo.resolve()),
        "content_repo_sha": git_sha(content_repo),
        "translator_repo_sha": git_sha(translator_repo),
        "config_fingerprint": _config_fingerprint(translator_repo),
        "model_fingerprints": {
            "model_registry": sha256_file(
                translator_repo / "config/model_registry.yaml"
            ),
        },
        "tm_fingerprint": fingerprint_files(
            translator_repo,
            [
                "data/tm/l2_lmdb/data.mdb",
                "data/tm/l3_faiss/index.faiss",
                "data/tm/l3_faiss/metadata.pkl",
                "data/tm/l3_faiss/config.json",
            ],
        ),
        "target_locales": list(TARGET_LOCALES),
        "expected_source_count": EXPECTED_SOURCE_COUNT,
        "expected_output_count": EXPECTED_OUTPUT_COUNT,
        "retry_policy": {
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        "commit_policy": {
            "branch": "pilot/foss-localization-zero-defect",
            "max_outputs_per_commit": 250,
            "push": False,
        },
        "sources": sources,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--content-repo",
        type=Path,
        default=Path(os.environ.get("ASPOSE_ORG_REPO", "D:/onedrive/Documents/GitHub/aspose.org")),
    )
    parser.add_argument("--translator-repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/campaigns/aspose-foss-25-locales.yaml"),
    )
    parser.add_argument(
        "--campaign-id",
        default="aspose-foss-25-locales-v1",
    )
    args = parser.parse_args(argv)

    try:
        payload = build_manifest(
            content_repo=args.content_repo.resolve(),
            translator_repo=args.translator_repo.resolve(),
            campaign_id=args.campaign_id,
        )
    except Exception as exc:
        print(f"MANIFEST BUILD BLOCKED: {exc}", file=sys.stderr)
        return 1

    atomic_write(
        path=args.output,
        content=yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        fsync=True,
        create_parents=True,
    )
    print(
        f"Wrote {args.output}: {payload['expected_source_count']} sources, "
        f"{payload['expected_output_count']} outputs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
