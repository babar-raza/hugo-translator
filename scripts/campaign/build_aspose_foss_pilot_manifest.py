"""Build the pinned Aspose FOSS 25-locale campaign manifest.

The builder refuses dirty repositories because a manifest generated from
uncommitted state cannot provide an immutable translation baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import yaml

from src.utils.atomic_write import atomic_write
from src.workers.campaign_manifest import (
    dirty_path_fingerprints,
    dirty_snapshot_fingerprint,
    fingerprint_files,
    git_dirty_paths,
    git_sha,
    sha256_file,
)

TARGET_LOCALES = (
    "ar",
    "cs",
    "de",
    "el",
    "es",
    "fa",
    "fr",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "nl",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh",
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
    paths = [
        translator_repo / "config/global.yaml",
        translator_repo / "config/validation.yaml",
        translator_repo / "config/terminology.yaml",
        translator_repo / "config/terminology/technical_terms.yaml",
        translator_repo / "config/site_profiles/default.yaml",
    ]
    paths.extend(
        translator_repo / "config/site_profiles" / f"{site}.yaml" for site, _ in FOLDER_SURFACES
    )
    paths.append(translator_repo / "config/site_profiles/blog.aspose.org.yaml")
    for path in paths:
        digest.update(path.relative_to(translator_repo).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _knowledge_fingerprints(content_repo: Path) -> dict[str, str]:
    paths: list[Path] = []
    for family, platform in PRODUCTS:
        merged = Path("knowledge") / family / platform / "merged"
        paths.extend(
            [
                merged / "model.yaml",
                merged / "claims.json",
                merged / "api_surface.json",
            ]
        )
    paths.append(Path("knowledge/html/python/scout/enriched_claims.json"))
    paths.extend(
        [
            Path("reports/generation/words-net.yaml"),
            Path("reports/generation/html-python.yaml"),
            Path("reports/generation/cells-rust.yaml"),
            Path("reports/grade_manifest.json"),
        ]
    )
    return {path.as_posix(): sha256_file(content_repo / path) for path in paths}


def _accepted_output_hashes(receipts_path: Path | None) -> dict[str, str]:
    """Load only validated metadata from an existing acceptance ledger."""
    if receipts_path is None:
        return {}
    if not receipts_path.is_file():
        raise RuntimeError(f"accepted receipt ledger missing: {receipts_path}")
    accepted: dict[str, str] = {}
    for line_number, line in enumerate(receipts_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            receipt = json.loads(line)
            output = Path(str(receipt["output_path"])).as_posix()
            output_hash = str(receipt["output_sha256"])
            gates = receipt["gate_results"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid acceptance receipt at line {line_number}: {exc}") from exc
        if (
            Path(output).is_absolute()
            or ".." in Path(output).parts
            or len(output_hash) != 64
            or len(gates) != 44
            or any(not isinstance(value, dict) or value.get("passed") is not True for value in gates.values())
            or "content" in receipt
            or "translated_content" in receipt
        ):
            raise RuntimeError(f"invalid zero-defect receipt at line {line_number}")
        previous = accepted.setdefault(output, output_hash)
        if previous != output_hash:
            raise RuntimeError(f"conflicting accepted output receipt: {output}")
    return accepted


def _folder_sources(content_repo: Path):
    for site_id, default_wave in FOLDER_SURFACES:
        for family, platform in PRODUCTS:
            root = content_repo / "content" / site_id / "en" / family / platform
            for source in sorted(root.rglob("*.md")):
                relative_tail = source.relative_to(root)
                source_rel = source.relative_to(content_repo).as_posix()
                outputs = {
                    locale: (
                        Path("content") / site_id / locale / family / platform / relative_tail
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
                locale: source.with_name(f"{source.stem}.{locale}{source.suffix}")
                .relative_to(content_repo)
                .as_posix()
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
    allow_dirty_content: bool = False,
    accepted_output_hashes: dict[str, str] | None = None,
) -> dict:
    content_dirty = git_dirty_paths(content_repo)
    translator_dirty = git_dirty_paths(translator_repo)
    accepted_output_hashes = accepted_output_hashes or {}
    if translator_dirty or (content_dirty and not allow_dirty_content):
        raise RuntimeError(
            "Immutable manifest requires clean repositories: "
            f"content_dirty={len(content_dirty)}, translator_dirty={len(translator_dirty)}"
        )
    if allow_dirty_content and not accepted_output_hashes:
        raise RuntimeError("dirty content destination requires an accepted receipt ledger")

    sources = [*_folder_sources(content_repo), *_blog_sources(content_repo)]
    output_count = sum(len(item["outputs"]) for item in sources)
    if len(sources) != EXPECTED_SOURCE_COUNT or output_count != EXPECTED_OUTPUT_COUNT:
        raise RuntimeError(
            "Campaign denominator drift: "
            f"sources={len(sources)}/{EXPECTED_SOURCE_COUNT}, "
            f"outputs={output_count}/{EXPECTED_OUTPUT_COUNT}"
        )

    allowed_outputs = {
        output for source in sources for output in source["outputs"].values()
    }
    unexpected_receipts = sorted(set(accepted_output_hashes) - allowed_outputs)
    if unexpected_receipts:
        raise RuntimeError(
            f"accepted receipt outside campaign matrix: {unexpected_receipts[0]}"
        )
    for output, output_hash in accepted_output_hashes.items():
        output_path = content_repo / output
        if not output_path.is_file():
            raise RuntimeError(f"accepted receipt output missing from destination: {output}")
        if sha256_file(output_path) != output_hash:
            raise RuntimeError(f"accepted receipt output hash mismatch: {output}")
    existing_without_receipt = [
        output for output in allowed_outputs
        if (content_repo / output).exists() and output not in accepted_output_hashes
    ]
    if existing_without_receipt:
        raise RuntimeError(
            f"destination contains unreceipted campaign output: {existing_without_receipt[0]}"
        )
    destination_baseline = {}
    if allow_dirty_content:
        paths = dirty_path_fingerprints(
            content_repo,
            exclude_paths=set(accepted_output_hashes),
        )
        destination_baseline = {
            "repo_head": git_sha(content_repo),
            "paths": paths,
            "fingerprint": dirty_snapshot_fingerprint(paths),
        }

    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo.resolve()),
        "content_repo_sha": git_sha(content_repo),
        "translator_repo_sha": git_sha(translator_repo),
        "config_fingerprint": _config_fingerprint(translator_repo),
        "model_fingerprints": {
            "model_registry": sha256_file(translator_repo / "config/model_registry.yaml"),
        },
        "tm_fingerprint": fingerprint_files(
            translator_repo,
            [
                "data/tm/l2.lmdb/data.mdb",
                "data/tm/l3_faiss/index.faiss",
                "data/tm/l3_faiss/metadata.pkl",
                "data/tm/l3_faiss/config.json",
            ],
        ),
        "knowledge_fingerprints": _knowledge_fingerprints(content_repo),
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
            "enabled": not allow_dirty_content,
        },
        # Four candidate pipelines share one CUDA-resident model.  This is
        # deliberately capped: parallelism is for CPU parsing/validation and
        # remote judgement overlap, never duplicate MT model residency.
        "execution_policy": {
            "max_parallel_jobs": 4,
            "model_sharing": "single_shared_instance",
        },
        "destination_baseline": destination_baseline,
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
    parser.add_argument(
        "--accepted-receipts",
        type=Path,
        help="metadata-only ledger for already accepted direct-destination outputs",
    )
    parser.add_argument(
        "--allow-dirty-content",
        action="store_true",
        help="freeze unrelated destination changes instead of requiring a clean content repository",
    )
    args = parser.parse_args(argv)

    try:
        payload = build_manifest(
            content_repo=args.content_repo.resolve(),
            translator_repo=args.translator_repo.resolve(),
            campaign_id=args.campaign_id,
            allow_dirty_content=args.allow_dirty_content,
            accepted_output_hashes=_accepted_output_hashes(args.accepted_receipts),
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
