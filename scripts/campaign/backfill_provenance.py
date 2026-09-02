"""One-time provenance backfill: populate per-site MetadataTracker files and the work ledger (TC-APT-003).

Mission ``aspose-org-full-portfolio-translation-20260901``, plan sections 7.1, 7.4, 14.1.

For every in-scope site:

1. governed discovery (``build_campaign_manifest.discover_sources``) -> the source set and
   every expected target path (engine-computed);
2. the site's **extended** ``MetadataTracker`` (``sha256`` algorithm, keyed relative to the
   content repo) records each source's SHA256 + the current profile/protection fingerprints,
   and registers each *existing* target's bytes with ``status=unknown_provenance``;
3. provenance tiers (strongest first): ``RECEIPT_BACKED`` (path+sha256 in any historical
   ``data/campaigns/*/acceptance_receipts.jsonl``) -> ``GIT_COMMIT_BACKED``
   (``git_provenance.classify_bulk``: governed one-file add commits) -> ``UNKNOWN``;
4. one ledger row per (source, target_lang) cell -- for the 25 allowlisted locales AND the
   profile-excluded locales (recorded as ``EXCLUDED_BY_PROFILE``, never acted on).

Initial eligibility (the full precedence algorithm is TC-APT-007; this backfill only sets
what provenance alone can justify):

* locale not in the profile allowlist          -> EXCLUDED_BY_PROFILE
* source empty                                  -> SOURCE_INVALID
* target absent                                 -> MISSING_TRANSLATION
* RECEIPT_BACKED, receipt source == current      -> UP_TO_DATE
* RECEIPT_BACKED, receipt source != current      -> SOURCE_CHANGED
* GIT_COMMIT_BACKED (no receipt => no source sha) -> UNKNOWN_PROVENANCE (runner recovery revalidates)
* otherwise                                      -> UNKNOWN_PROVENANCE (plan 7.4 audit sampling)

The ledger never recomputes hashes: every ``source_sha256``/``target_sha256`` it stores is
read back from the tracker after the tracker recorded it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.campaign.build_campaign_manifest import (
    IN_SCOPE_SITES,
    discover_sources,
    load_known_language_codes,
    load_profiles,
)
from src.utils.atomic_write import atomic_write
from src.utils.content_discovery import resolve_translated_path
from src.utils.content_hash import compute_file_hash
from src.utils.metadata_tracker import MetadataTracker
from src.workers import git_provenance
from src.workers.fingerprints import site_fingerprints
from src.workers.work_ledger import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_METADATA_DIR,
    WorkLedger,
    metadata_path_for_site,
)

DEFAULT_SUMMARY_OUTPUT = Path("data/campaigns/backfill_provenance_summary.json")


# --------------------------------------------------------------------------- receipts
def load_receipt_index(receipt_files: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """``output_path -> receipt`` for every all-pass receipt in the given ledgers."""
    index: dict[str, dict[str, Any]] = {}
    for path in receipt_files:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                receipt = json.loads(line)
            except json.JSONDecodeError:
                continue
            output = str(receipt.get("output_path", "")).replace("\\", "/")
            if not output or "content" in receipt or "translated_content" in receipt:
                continue
            gates = receipt.get("gate_results") or {}
            if any(not isinstance(v, dict) or not v.get("passed") for v in gates.values()):
                continue
            index[output] = {**receipt, "_ledger": path.as_posix()}
    return index


def default_receipt_files(translator_repo: Path) -> list[Path]:
    return sorted((translator_repo / "data/campaigns").glob("*/acceptance_receipts.jsonl"))


# --------------------------------------------------------------------------- hashing
def _hash_many(paths: list[Path], workers: int) -> dict[Path, str]:
    if not paths:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        digests = pool.map(lambda p: compute_file_hash(p, "sha256"), paths)
        return dict(zip(paths, digests))


# --------------------------------------------------------------------------- per-site
def backfill_site(
    *,
    content_repo: Path,
    translator_repo: Path,
    profile: Any,
    known_codes: tuple[str, ...],
    metadata_dir: Path,
    receipts: dict[str, dict[str, Any]],
    workers: int = 8,
    git_provenance_enabled: bool = True,
    include_excluded_locales: bool = True,
) -> tuple[list[dict[str, Any]], MetadataTracker, dict[str, Any]]:
    """Populate one site's tracker and return its ledger rows + facts."""
    t0 = time.time()
    content_repo = content_repo.resolve()
    fps = site_fingerprints(profile, translator_repo)
    sources, facts = discover_sources(content_repo, profile, known_codes, hash_sources=False)

    tracker = MetadataTracker(
        metadata_path_for_site(profile.site_id, metadata_dir),
        hash_algorithm="sha256",
        site_id=profile.site_id,
        root=content_repo,
    )
    tracker.load()

    # 1) sources: hash in parallel, record through the tracker
    source_abs = [content_repo / s["source_path"] for s in sources]
    source_sha = _hash_many(source_abs, workers)
    for s, abs_path in zip(sources, source_abs):
        tracker.update_source(
            abs_path,
            profile_fingerprint=fps["profile_fingerprint"],
            protection_fingerprint=fps["protection_fingerprint"],
            sha256=source_sha[abs_path],
        )

    # 2) existing targets (allowlisted locales): hash in parallel, register as unknown provenance
    existing: list[tuple[dict[str, Any], str, Path]] = []
    for s in sources:
        for lang, rel in s["outputs"].items():
            target = content_repo / rel
            if target.is_file():
                existing.append((s, lang, target))
    target_sha = _hash_many([t for _, _, t in existing], workers)
    for s, lang, target in existing:
        tracker.record_existing_output(
            content_repo / s["source_path"], target, lang, sha256=target_sha[target]
        )
    tracker.save()

    # 3) provenance tiers
    rel_to_sha = {t.relative_to(content_repo).as_posix(): target_sha[t] for _, _, t in existing}
    git_result: dict[str, Any] = {}
    if git_provenance_enabled and rel_to_sha:
        git_result = git_provenance.classify_bulk(content_repo, rel_to_sha)

    # 4) rows -- read hashes BACK from the tracker (the ledger never recomputes)
    rows: list[dict[str, Any]] = []
    excluded_codes = sorted(
        set(known_codes) - set(profile.target_langs) - {profile.default_source_lang}
    )
    for s in sources:
        abs_source = content_repo / s["source_path"]
        entry = tracker.entries()[tracker.key_for(abs_source)]
        src_sha = entry.source.sha256
        source_empty = entry.source.size_bytes == 0
        langs: list[tuple[str, str, bool]] = [
            (lang, rel, True) for lang, rel in s["outputs"].items()
        ]
        if include_excluded_locales:
            for code in excluded_codes:
                rel = (
                    Path(resolve_translated_path(profile, abs_source, code))
                    .resolve()
                    .relative_to(content_repo)
                    .as_posix()
                )
                langs.append((code, rel, False))
        for lang, rel, allowlisted in langs:
            out_meta = entry.outputs.get(lang) if allowlisted else None
            target_path = content_repo / rel
            target_exists = target_path.is_file()
            row: dict[str, Any] = {
                "site_id": profile.site_id,
                "family": s["family"],
                "platform": s["platform"],
                "source_path": s["source_path"],
                "target_lang": lang,
                "expected_output_path": rel,
                "source_sha256": src_sha,
                "profile_fingerprint": fps["profile_fingerprint"],
                "protection_fingerprint": fps["protection_fingerprint"],
                "target_exists": target_exists,
                "target_sha256": out_meta.sha256 if out_meta else None,
                "provenance_kind": "UNKNOWN",
                "provenance_ref": None,
                "provenance_source_sha256": None,
                "wave": 0,
            }
            if not allowlisted:
                row.update(
                    eligibility_state="EXCLUDED_BY_PROFILE",
                    eligibility_reason_code="locale_not_in_profile_allowlist",
                )
            elif source_empty:
                row.update(
                    eligibility_state="SOURCE_INVALID", eligibility_reason_code="empty_source"
                )
            elif not target_exists:
                row.update(
                    eligibility_state="MISSING_TRANSLATION", eligibility_reason_code="target_absent"
                )
            else:
                receipt = receipts.get(rel)
                if receipt and receipt.get("output_sha256") == row["target_sha256"]:
                    row.update(
                        provenance_kind="RECEIPT_BACKED",
                        provenance_ref=f"{receipt['_ledger']}#{receipt.get('receipt_sha256', '')}",
                        provenance_source_sha256=receipt.get("source_sha256"),
                        tm_lineage_config_fp=receipt.get("config_fingerprint"),
                    )
                    if receipt.get("source_sha256") == src_sha:
                        row.update(
                            eligibility_state="UP_TO_DATE",
                            eligibility_reason_code="receipt_source_match",
                        )
                    else:
                        row.update(
                            eligibility_state="SOURCE_CHANGED",
                            eligibility_reason_code="receipt_source_drift",
                        )
                else:
                    verdict = git_result.get(rel)
                    if isinstance(verdict, git_provenance.GovernedCommit):
                        row.update(
                            provenance_kind="GIT_COMMIT_BACKED",
                            provenance_ref=f"git:{verdict.commit_sha}",
                            eligibility_state="UNKNOWN_PROVENANCE",
                            eligibility_reason_code="git_commit_backed_receipt_missing",
                        )
                    else:
                        row.update(
                            eligibility_state="UNKNOWN_PROVENANCE",
                            eligibility_reason_code="no_trustworthy_provenance",
                        )
            rows.append(row)

    facts.update(
        {
            "profile_fingerprint": fps["profile_fingerprint"],
            "protection_fingerprint": fps["protection_fingerprint"],
            "existing_targets_hashed": len(existing),
            "git_governed_commits": sum(
                1 for v in git_result.values() if isinstance(v, git_provenance.GovernedCommit)
            ),
            "receipt_backed": sum(1 for r in rows if r["provenance_kind"] == "RECEIPT_BACKED"),
            "rows": len(rows),
            "metadata_file": tracker.metadata_file.as_posix(),
            "seconds": round(time.time() - t0, 1),
        }
    )
    return rows, tracker, facts


# --------------------------------------------------------------------------- verification
def ledger_matches_tracker(
    ledger: WorkLedger, tracker: MetadataTracker, *, sample: int | None = None
) -> list[str]:
    """Return mismatches between ledger hashes and the tracker's own records (acceptance check)."""
    problems: list[str] = []
    entries = tracker.entries()
    site_id = tracker.site_id
    checked = 0
    for key, meta in entries.items():
        for row in ledger.query(site_id=site_id):
            if row["source_path"] != key:
                continue
            if row["source_sha256"] != meta.source.sha256:
                problems.append(f"{key}: source sha mismatch")
            out = meta.outputs.get(row["target_lang"])
            if out is not None and row["target_sha256"] != out.sha256:
                problems.append(f"{key}[{row['target_lang']}]: target sha mismatch")
            if (
                out is None
                and row["target_exists"]
                and row["eligibility_state"] not in ("EXCLUDED_BY_PROFILE",)
            ):
                problems.append(f"{key}[{row['target_lang']}]: exists in ledger but not in tracker")
            checked += 1
        if sample is not None and checked >= sample:
            break
    return problems


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-003 provenance backfill")
    parser.add_argument(
        "--content-repo",
        type=Path,
        default=Path(os.environ.get("ASPOSE_ORG_REPO", "D:/onedrive/Documents/GitHub/aspose.org")),
    )
    parser.add_argument("--translator-repo", type=Path, default=Path.cwd())
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-git-provenance", action="store_true")
    parser.add_argument("--no-excluded-locales", action="store_true")
    args = parser.parse_args(argv)

    t0 = time.time()
    translator_repo = args.translator_repo.resolve()
    content_repo = args.content_repo.resolve()
    sites = tuple(args.sites) if args.sites else IN_SCOPE_SITES
    known = load_known_language_codes(translator_repo)
    profiles = load_profiles(translator_repo, content_repo, sites)
    receipts = load_receipt_index(default_receipt_files(translator_repo))

    summary: dict[str, Any] = {
        "taskcard": "TC-APT-003",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "content_repo": content_repo.as_posix(),
        "content_repo_sha": git_provenance._run(
            content_repo, ["rev-parse", "HEAD"], text=True
        ).stdout.strip(),
        "receipt_ledgers_scanned": [p.as_posix() for p in default_receipt_files(translator_repo)],
        "receipts_indexed": len(receipts),
        "sites": {},
    }
    with WorkLedger(args.ledger) as ledger:
        for site_id in sorted(profiles):
            rows, tracker, facts = backfill_site(
                content_repo=content_repo,
                translator_repo=translator_repo,
                profile=profiles[site_id],
                known_codes=known,
                metadata_dir=args.metadata_dir,
                receipts=receipts,
                workers=args.workers,
                git_provenance_enabled=not args.no_git_provenance,
                include_excluded_locales=not args.no_excluded_locales,
            )
            written = ledger.bulk_upsert(rows, reason="TC-APT-003 provenance backfill")
            mismatches = ledger_matches_tracker(ledger, tracker, sample=200)
            facts["ledger_rows_written"] = written
            facts["tracker_ledger_mismatches_sample200"] = mismatches[:10]
            facts["states"] = ledger.counts_by_state(site_id=site_id)
            summary["sites"][site_id] = facts
            print(
                f"{site_id}: rows={written} states={facts['states']} git_governed={facts['git_governed_commits']} receipt_backed={facts['receipt_backed']} {facts['seconds']}s",
                flush=True,
            )
        summary["totals"] = {
            "rows": ledger.total(),
            "duplicate_cells": ledger.duplicate_cells(),
            "states": ledger.counts_by_state(),
            "by_site": ledger.counts_by_site_state(),
        }
    summary["seconds"] = round(time.time() - t0, 1)
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(path=args.summary_output, content=json.dumps(summary, indent=2))
    print(
        f"ledger {args.ledger}: rows={summary['totals']['rows']} dup_cells={summary['totals']['duplicate_cells']} states={summary['totals']['states']} ({summary['seconds']}s)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
