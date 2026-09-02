"""Build the full-portfolio inventory and governed campaign manifests (TC-APT-002).

Mission ``aspose-org-full-portfolio-translation-20260901`` -- generalizes
``build_aspose_foss_pilot_manifest.py`` from 3 product/platform slices to the **6 in-scope
aspose.org sites** (``www.aspose.org`` is out of scope by operator decision, plan section 1).

Discovery is the *governed* path, not ad hoc ``find``:

* each site's ``SiteProfile`` supplies its content root, source language, layout and the
  hard 25-locale allowlist (``strict_locale_allowlist``);
* ``src/utils/file_filters.filter_source_files`` decides what is a source (it is given the
  full 36-code language registry so legacy ``index.bg.md`` siblings in the 11 excluded
  locales are never mistaken for sources);
* ``src/utils/content_discovery.resolve_translated_path`` -- the engine's own output-path
  logic -- computes every expected target path (never reimplemented here).

Outputs:

* ``config/inventory/aspose_org_profile_inventory.json`` -- exact counts per
  site/family/platform, existing-target coverage per locale, excluded-locale legacy
  presence, and a reconciliation against the plan's section-4 coarse estimate (any site
  with a >20% delta is flagged ``investigate``).
* optionally a ``CampaignManifest`` YAML (schema_version 1, zero-defect) scoped by
  ``--family/--platform/--source-prefix/--source-list/--max-sources`` for Gates 4-8.

The ``config_fingerprint`` recipe follows the pilot builder **minus** the dead
``config/site_profiles/default.yaml`` (plan G-08, DECIDED: never read by code, hashing it
only produced spurious invalidations).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from src.utils.atomic_write import atomic_write
from src.utils.content_discovery import resolve_translated_path
from src.utils.file_filters import filter_source_files
from src.workers.campaign_manifest import (
    fingerprint_files,
    git_dirty_paths,
    git_sha,
    sha256_file,
)

IN_SCOPE_SITES: tuple[str, ...] = (
    "blog.aspose.org",
    "docs.aspose.org",
    "kb.aspose.org",
    "products.aspose.org",
    "reference.aspose.org",
    "websites.aspose.org",
)
OUT_OF_SCOPE_SITES: tuple[str, ...] = ("www.aspose.org",)

#: Plan section 4 coarse measurement (2026-09-01), superseded by this script's exact count.
PLAN_SECTION4_ESTIMATE: dict[str, int] = {
    "reference.aspose.org": 8042,
    "docs.aspose.org": 519,
    "kb.aspose.org": 367,
    "products.aspose.org": 59,
    "websites.aspose.org": 15,
    "blog.aspose.org": 157,
}
RECONCILE_DELTA_THRESHOLD = 0.20

DEFAULT_INVENTORY_OUTPUT = Path("config/inventory/aspose_org_profile_inventory.json")

CONFIG_FINGERPRINT_SHARED = (
    "config/global.yaml",
    "config/validation.yaml",
    "config/terminology.yaml",
    "config/terminology/technical_terms.yaml",
    "config/terminology/aspose_terms.txt",
)
#: TM artifacts bound into a manifest. L2 is mandatory; the L3 files are hashed only when
#: present (the L3 index is rebuilt on demand and is absent on this host as of 2026-09-02).
TM_FINGERPRINT_REQUIRED = ("data/tm/l2.lmdb/data.mdb",)
TM_FINGERPRINT_OPTIONAL = (
    "data/tm/l3_faiss/index.faiss",
    "data/tm/l3_faiss/metadata.pkl",
    "data/tm/l3_faiss/config.json",
)


def tm_fingerprint_inputs(translator_repo: Path) -> list[str]:
    missing = [rel for rel in TM_FINGERPRINT_REQUIRED if not (translator_repo / rel).is_file()]
    if missing:
        raise DiscoveryError(f"required TM artifact missing: {missing}")
    present = [rel for rel in TM_FINGERPRINT_OPTIONAL if (translator_repo / rel).is_file()]
    return [*TM_FINGERPRINT_REQUIRED, *present]


class DiscoveryError(RuntimeError):
    """Raised when the governed discovery cannot produce a trustworthy inventory."""


# --------------------------------------------------------------------------- config inputs
def load_known_language_codes(translator_repo: Path) -> tuple[str, ...]:
    """All language codes the system knows (36), from ``config/target_languages.yaml``."""
    path = translator_repo / "config/target_languages.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    codes = [str(item["iso_code"]) for item in data.get("languages", [])]
    if len(codes) < 2:
        raise DiscoveryError(f"no languages in {path}")
    return tuple(sorted(set(codes)))


def load_profiles(
    translator_repo: Path, content_repo: Path, sites: Iterable[str]
) -> dict[str, Any]:
    """Load ``SiteProfile`` objects through ``ConfigService`` with the content root pinned.

    ``--content-repo`` is authoritative: ``ASPOSE_ORG_CONTENT`` is set from it so the
    profiles' ``${ASPOSE_ORG_CONTENT}`` roots resolve deterministically regardless of
    ``.env``.
    """
    from src.utils.config_loader import ConfigService

    sites = list(sites)
    for site_id in sites:
        if site_id in OUT_OF_SCOPE_SITES:
            raise DiscoveryError(f"{site_id} is out of mission scope (plan section 1)")
    os.environ["ASPOSE_ORG_CONTENT"] = (content_repo / "content").resolve().as_posix()
    service = ConfigService(translator_repo / "config")
    return {site_id: service.get_site_profile(site_id) for site_id in sites}


def config_fingerprint(translator_repo: Path, sites: Iterable[str]) -> str:
    """Hash the shared config artifacts + each in-scope profile. Excludes default.yaml (G-08)."""
    digest = hashlib.sha256()
    paths = [translator_repo / rel for rel in CONFIG_FINGERPRINT_SHARED]
    paths.extend(
        translator_repo / "config/site_profiles" / f"{site}.yaml" for site in sorted(sites)
    )
    for path in paths:
        if not path.is_file():
            raise DiscoveryError(f"config fingerprint input missing: {path}")
        digest.update(path.relative_to(translator_repo).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


# --------------------------------------------------------------------------- discovery
def resolve_site_root(profile: Any) -> Path:
    roots = [Path(os.path.expandvars(str(r))).expanduser() for r in profile.content_roots]
    if len(roots) != 1:
        raise DiscoveryError(f"{profile.site_id}: expected exactly one content root, got {roots}")
    root = roots[0]
    if not root.is_dir():
        raise DiscoveryError(f"{profile.site_id}: content root missing: {root}")
    return root


def _per_language_folders(profile: Any) -> bool:
    layout = getattr(profile, "output_layout", None)
    return bool(getattr(layout, "per_language_folders", False)) if layout else False


def family_platform(
    relative_parts: tuple[str, ...], *, per_language_folders: bool, source_lang: str
) -> tuple[str, str]:
    """Derive (family, platform) from a source path relative to the site root.

    Folder sites: ``en/<family>/<platform>/...``; blog (file-based): ``<family>/<platform>/...``.
    Section/root pages (``en/_index.md``, ``en/cells/_index.md``) get ``''`` for the missing level.
    """
    dirs = list(relative_parts[:-1])
    if per_language_folders and dirs and dirs[0] == source_lang:
        dirs = dirs[1:]
    family = dirs[0] if len(dirs) >= 1 else ""
    platform = dirs[1] if len(dirs) >= 2 else ""
    return family, platform


def discover_sources(
    content_repo: Path,
    profile: Any,
    known_codes: tuple[str, ...],
    *,
    hash_sources: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Governed discovery for one site.

    Returns ``(sources, scan_facts)`` where each source carries ``site_id, family, platform,
    source_path, source_sha256, outputs{locale: path}, wave`` (all paths content-repo-relative
    POSIX) and ``scan_facts`` records what the scan saw (all markdown, excluded-locale legacy).
    """
    root = resolve_site_root(profile)
    content_repo = content_repo.resolve()
    per_lang = _per_language_folders(profile)
    source_lang = str(getattr(profile, "default_source_lang", "en"))
    target_langs = [str(code) for code in profile.target_langs]
    all_md = sorted(p for p in root.rglob("*.md") if p.is_file())
    # Governed source filter, fed the FULL registry so any known-language suffix/folder
    # (including the 11 profile-excluded legacy locales) is excluded from the source set.
    sources_abs = filter_source_files(list(all_md), profile, list(known_codes), source_lang)

    excluded_codes = sorted(set(known_codes) - set(target_langs) - {source_lang})
    legacy: dict[str, int] = {}
    if per_lang:
        for code in excluded_codes:
            code_dir = root / code
            if code_dir.is_dir():
                legacy[code] = sum(1 for _ in code_dir.rglob("*.md"))
    else:
        suffix_counts = Counter(p.suffixes[-2].lstrip(".") for p in all_md if len(p.suffixes) >= 2)
        legacy = {code: suffix_counts[code] for code in excluded_codes if suffix_counts.get(code)}

    sources: list[dict[str, Any]] = []
    seen_outputs: set[str] = set()
    for source in sources_abs:
        rel_root = source.relative_to(root)
        family, platform = family_platform(
            rel_root.parts, per_language_folders=per_lang, source_lang=source_lang
        )
        source_rel = source.resolve().relative_to(content_repo).as_posix()
        outputs: dict[str, str] = {}
        for lang in target_langs:
            target = Path(resolve_translated_path(profile, source, lang)).resolve()
            try:
                target_rel = target.relative_to(content_repo).as_posix()
            except ValueError as exc:
                raise DiscoveryError(
                    f"{source_rel}: output outside content repo: {target}"
                ) from exc
            if target_rel == source_rel:
                raise DiscoveryError(f"{source_rel}: output path equals source path for {lang}")
            if target_rel in seen_outputs:
                raise DiscoveryError(f"duplicate output path: {target_rel}")
            seen_outputs.add(target_rel)
            outputs[lang] = target_rel
        sources.append(
            {
                "site_id": profile.site_id,
                "family": family,
                "platform": platform,
                "source_path": source_rel,
                "source_sha256": sha256_file(source) if hash_sources else "",
                "outputs": outputs,
                "wave": 0,
            }
        )
    facts = {
        "content_root": root.as_posix(),
        "layout": "per_language_folders" if per_lang else "file_suffix",
        "source_lang": source_lang,
        "target_langs": target_langs,
        "markdown_files_seen": len(all_md),
        "sources_after_governed_filter": len(sources),
        "excluded_locale_legacy_files": legacy,
    }
    return sources, facts


# --------------------------------------------------------------------------- inventory
def build_inventory(
    content_repo: Path,
    translator_repo: Path,
    profiles: dict[str, Any],
    known_codes: tuple[str, ...],
    *,
    check_existing_targets: bool = True,
    hash_sources: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Exact per-site/family/platform inventory plus the flat source list it was built from."""
    content_repo = content_repo.resolve()
    all_sources: list[dict[str, Any]] = []
    sites_out: dict[str, Any] = {}
    locale_sets: dict[str, tuple[str, ...]] = {}
    for site_id in sorted(profiles):
        profile = profiles[site_id]
        sources, facts = discover_sources(
            content_repo, profile, known_codes, hash_sources=hash_sources
        )
        locale_sets[site_id] = tuple(facts["target_langs"])
        by_family: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in sources:
            by_family[item["family"]][item["platform"]] += 1
        existing_by_lang: dict[str, int] = {}
        if check_existing_targets:
            counts: Counter[str] = Counter()
            for item in sources:
                for lang, rel in item["outputs"].items():
                    if (content_repo / rel).is_file():
                        counts[lang] += 1
            existing_by_lang = {lang: counts.get(lang, 0) for lang in facts["target_langs"]}
        n_sources = len(sources)
        n_langs = len(facts["target_langs"])
        estimate = PLAN_SECTION4_ESTIMATE.get(site_id)
        delta = None if not estimate else (n_sources - estimate) / estimate
        sites_out[site_id] = {
            **facts,
            "source_count": n_sources,
            "target_lang_count": n_langs,
            "cell_count": n_sources * n_langs,
            "families": {
                fam: {"platforms": dict(sorted(plats.items())), "source_count": sum(plats.values())}
                for fam, plats in sorted(by_family.items())
            },
            "existing_targets_by_lang": existing_by_lang,
            "existing_target_cells": sum(existing_by_lang.values()),
            "missing_target_cells": n_sources * n_langs - sum(existing_by_lang.values()),
            "reconciliation_vs_plan_section4": {
                "plan_estimate": estimate,
                "exact": n_sources,
                "delta_ratio": None if delta is None else round(delta, 4),
                "disposition": (
                    "no_estimate"
                    if delta is None
                    else "investigate"
                    if abs(delta) > RECONCILE_DELTA_THRESHOLD
                    else "reconciled"
                ),
            },
        }
        all_sources.extend(sources)

    distinct_locale_sets = {v for v in locale_sets.values()}
    inventory = {
        "schema_version": 1,
        "mission_id": "aspose-org-full-portfolio-translation-20260901",
        "taskcard": "TC-APT-002",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_repo": content_repo.as_posix(),
        "content_repo_sha": _safe_git_sha(content_repo),
        "content_repo_dirty_paths": _safe_dirty_count(content_repo),
        "translator_repo_sha": _safe_git_sha(translator_repo),
        "known_language_codes": list(known_codes),
        "in_scope_sites": sorted(profiles),
        "out_of_scope_sites": list(OUT_OF_SCOPE_SITES),
        "locale_set_consistent_across_sites": len(distinct_locale_sets) == 1,
        "portfolio_target_langs": sorted(next(iter(distinct_locale_sets)))
        if len(distinct_locale_sets) == 1
        else None,
        "totals": {
            "source_count": sum(s["source_count"] for s in sites_out.values()),
            "cell_count": sum(s["cell_count"] for s in sites_out.values()),
            "existing_target_cells": sum(s["existing_target_cells"] for s in sites_out.values()),
            "missing_target_cells": sum(s["missing_target_cells"] for s in sites_out.values()),
            "plan_section4_source_estimate": sum(
                PLAN_SECTION4_ESTIMATE[s] for s in sites_out if s in PLAN_SECTION4_ESTIMATE
            ),
        },
        "sites": sites_out,
    }
    return inventory, all_sources


def _safe_git_sha(repo: Path) -> str | None:
    try:
        return git_sha(repo)
    except Exception:  # not a git checkout (tests) -- record absence, never fabricate
        return None


def _safe_dirty_count(repo: Path) -> int | None:
    try:
        return len(git_dirty_paths(repo))
    except Exception:
        return None


# --------------------------------------------------------------------------- manifest
def apply_scope(
    sources: list[dict[str, Any]],
    *,
    sites: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    platforms: Iterable[str] | None = None,
    source_prefixes: Iterable[str] | None = None,
    source_list: Iterable[str] | None = None,
    max_sources: int | None = None,
) -> list[dict[str, Any]]:
    sites_set = set(sites) if sites else None
    fam_set = set(families) if families else None
    plat_set = set(platforms) if platforms else None
    prefixes = tuple(source_prefixes) if source_prefixes else ()
    listed = set(source_list) if source_list else None
    out = []
    for item in sources:
        if sites_set and item["site_id"] not in sites_set:
            continue
        if fam_set and item["family"] not in fam_set:
            continue
        if plat_set and item["platform"] not in plat_set:
            continue
        if prefixes and not item["source_path"].startswith(prefixes):
            continue
        if listed is not None and item["source_path"] not in listed:
            continue
        out.append(item)
    out.sort(key=lambda s: (s["wave"], s["site_id"], s["source_path"]))
    if max_sources is not None:
        out = out[:max_sources]
    return out


def build_manifest(
    *,
    content_repo: Path,
    translator_repo: Path,
    campaign_id: str,
    sources: list[dict[str, Any]],
    target_locales: Iterable[str],
    sites: Iterable[str],
    locales: Iterable[str] | None = None,
    max_parallel_jobs: int = 1,
    dirty_scope: str = "campaign_paths",
    replace_existing: dict[str, dict[str, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Assemble a schema-1 zero-defect manifest (validated by ``CampaignManifest.load``).

    ``dirty_scope`` (TC-APT-032) defaults to ``campaign_paths`` for this shared content repo.
    ``replace_existing`` (TC-APT-031) maps source_path -> locale -> {expected_sha256, reason_code}
    for cells whose target already exists and is declared for governed replacement.

    ``locales`` (optional) narrows every source's outputs to a subset of the portfolio set
    (e.g. a Gate-4 canary cell); the manifest's ``target_locales`` then equals that subset.
    """
    locales_final = tuple(sorted(locales)) if locales else tuple(sorted(target_locales))
    portfolio = set(target_locales)
    unknown = set(locales_final) - portfolio
    if unknown:
        raise DiscoveryError(f"locales outside the profile allowlist: {sorted(unknown)}")
    scoped = []
    for item in sources:
        outputs = {lang: item["outputs"][lang] for lang in locales_final}
        entry = {**item, "outputs": outputs}
        declared = (replace_existing or {}).get(item["source_path"]) or {}
        entry["replace_existing"] = {
            lang: dict(spec) for lang, spec in declared.items() if lang in outputs
        }
        scoped.append(entry)
    if not scoped:
        raise DiscoveryError("manifest scope selected zero sources")
    output_count = sum(len(item["outputs"]) for item in scoped)
    sites = tuple(sorted(set(sites)))
    tm_inputs = tm_fingerprint_inputs(translator_repo)
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "validation_policy": "zero-defect",
        "content_repo": content_repo.resolve().as_posix(),
        "content_repo_sha": git_sha(content_repo),
        "translator_repo_sha": git_sha(translator_repo),
        "config_fingerprint": config_fingerprint(translator_repo, sites),
        "model_fingerprints": {
            "model_registry": sha256_file(translator_repo / "config/model_registry.yaml"),
        },
        "tm_fingerprint": fingerprint_files(translator_repo, tm_inputs),
        "tm_fingerprint_inputs": tm_inputs,
        "knowledge_fingerprints": {},
        "sites": list(sites),
        "target_locales": list(locales_final),
        "expected_source_count": len(scoped),
        "expected_output_count": output_count,
        # Strategy default until TC-APT-004b qualifies professionalize_llm as primary (plan 6.1).
        "retry_policy": {
            "primary_model": "m2m100_418m",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "professionalize_llm",
        },
        # hugo-translator never commits into the content repo; the loop does (plan 19.2).
        "commit_policy": {
            "branch": "main",
            "max_outputs_per_commit": 250,
            "push": False,
            "enabled": False,
        },
        # Concurrency above 1 is unlocked only by TC-APT-028's measured ceiling.
        "execution_policy": {
            "max_parallel_jobs": max_parallel_jobs,
            "model_sharing": "single_shared_instance",
            # TC-APT-032: only the campaign's own sources/outputs gate a run in a shared repo.
            "dirty_scope": dirty_scope,
        },
        "destination_baseline": {},
        "sources": scoped,
    }


def declarations_from_ledger(
    sources: list[dict[str, Any]],
    locales: Iterable[str],
    ledger_path: Path,
    *,
    content_repo: Path,
) -> dict[str, dict[str, dict[str, str]]]:
    """TC-APT-031: for every scoped cell whose target exists, declare a governed replacement.

    ``expected_sha256`` is the CURRENT on-disk hash (re-read now, cross-checked against the
    ledger's ``target_sha256`` when present); ``reason_code`` is the ledger's eligibility reason.
    """
    from src.workers.work_ledger import WorkLedger

    out: dict[str, dict[str, dict[str, str]]] = {}
    with WorkLedger(ledger_path) as ledger:
        for item in sources:
            for lang in locales:
                rel = item["outputs"].get(lang)
                if not rel:
                    continue
                target = content_repo / rel
                if not target.is_file():
                    continue
                current = sha256_file(target)
                row = ledger.get_cell(item["site_id"], item["source_path"], lang)
                reason = (row or {}).get("eligibility_reason_code") or "existing_target_undeclared"
                if row and row.get("target_sha256") and row["target_sha256"] != current:
                    reason = f"{reason};ledger_target_sha_stale"
                out.setdefault(item["source_path"], {})[lang] = {
                    "expected_sha256": current,
                    "reason_code": reason,
                }
    return out


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TC-APT-002 portfolio inventory / manifest builder"
    )
    parser.add_argument(
        "--content-repo",
        type=Path,
        default=Path(os.environ.get("ASPOSE_ORG_REPO", "D:/onedrive/Documents/GitHub/aspose.org")),
    )
    parser.add_argument("--translator-repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--site", action="append", dest="sites", help="restrict to site(s); default: all 6 in-scope"
    )
    parser.add_argument("--inventory-output", type=Path, default=DEFAULT_INVENTORY_OUTPUT)
    parser.add_argument(
        "--no-existing-check", action="store_true", help="skip on-disk target existence counting"
    )
    parser.add_argument(
        "--no-hash", action="store_true", help="skip source sha256 (inventory-only quick count)"
    )
    parser.add_argument("--manifest-output", type=Path, help="also write a campaign manifest YAML")
    parser.add_argument("--campaign-id")
    parser.add_argument("--family", action="append")
    parser.add_argument("--platform", action="append")
    parser.add_argument("--source-prefix", action="append")
    parser.add_argument(
        "--source-list", type=Path, help="file with one content-repo-relative source path per line"
    )
    parser.add_argument("--max-sources", type=int)
    parser.add_argument(
        "--locale",
        action="append",
        help="narrow outputs to these locales (subset of the allowlist)",
    )
    parser.add_argument("--max-parallel-jobs", type=int, default=1)
    parser.add_argument(
        "--dirty-scope", choices=("campaign_paths", "frozen_baseline"), default="campaign_paths"
    )
    parser.add_argument(
        "--existing",
        choices=("refuse", "replace"),
        default="refuse",
        help="refuse: existing targets are a hard stop (default); replace: declare governed replacement from the work ledger",
    )
    parser.add_argument("--ledger", type=Path, default=Path("data/campaigns/work_ledger.sqlite3"))
    args = parser.parse_args(argv)

    sites = tuple(args.sites) if args.sites else IN_SCOPE_SITES
    translator_repo = args.translator_repo.resolve()
    content_repo = args.content_repo.resolve()
    known_codes = load_known_language_codes(translator_repo)
    profiles = load_profiles(translator_repo, content_repo, sites)

    inventory, sources = build_inventory(
        content_repo,
        translator_repo,
        profiles,
        known_codes,
        check_existing_targets=not args.no_existing_check,
        hash_sources=not args.no_hash,
    )
    atomic_write(
        path=args.inventory_output, content=json.dumps(inventory, indent=2, ensure_ascii=False)
    )
    t = inventory["totals"]
    print(
        f"inventory -> {args.inventory_output}: sources={t['source_count']} cells={t['cell_count']} existing={t['existing_target_cells']} missing={t['missing_target_cells']}"
    )
    for site_id, s in inventory["sites"].items():
        r = s["reconciliation_vs_plan_section4"]
        print(
            f"  {site_id}: sources={s['source_count']} (plan {r['plan_estimate']}, delta {r['delta_ratio']}) -> {r['disposition']}; legacy excluded-locale files={sum(s['excluded_locale_legacy_files'].values())}"
        )

    if args.manifest_output:
        if not args.campaign_id:
            parser.error("--campaign-id is required with --manifest-output")
        if args.no_hash:
            parser.error("--no-hash cannot be combined with --manifest-output")
        if not inventory["locale_set_consistent_across_sites"]:
            raise DiscoveryError("sites disagree on target locales; refusing to build one manifest")
        listed = None
        if args.source_list:
            listed = [
                line.strip()
                for line in args.source_list.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        scoped = apply_scope(
            sources,
            families=args.family,
            platforms=args.platform,
            source_prefixes=args.source_prefix,
            source_list=listed,
            max_sources=args.max_sources,
        )
        declared = None
        if args.existing == "replace":
            declared = declarations_from_ledger(
                scoped,
                args.locale or inventory["portfolio_target_langs"],
                args.ledger,
                content_repo=content_repo,
            )
        manifest = build_manifest(
            content_repo=content_repo,
            translator_repo=translator_repo,
            campaign_id=args.campaign_id,
            sources=scoped,
            target_locales=inventory["portfolio_target_langs"],
            sites={item["site_id"] for item in scoped},
            locales=args.locale,
            max_parallel_jobs=args.max_parallel_jobs,
            dirty_scope=args.dirty_scope,
            replace_existing=declared,
        )
        atomic_write(
            path=args.manifest_output,
            content=yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        )
        print(
            f"manifest -> {args.manifest_output}: sources={manifest['expected_source_count']} outputs={manifest['expected_output_count']} locales={len(manifest['target_locales'])}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
