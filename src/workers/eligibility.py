"""Translation / retranslation eligibility algorithm (TC-APT-007, plan section 7.2 / 7.3 / 7.5).

Mission ``aspose-org-full-portfolio-translation-20260901``.

Classifies one (source, target_lang) cell into exactly one of the 13 eligibility states with a
strict precedence (first match wins):

 1. UNSUPPORTED_LANGUAGE      -- target_lang not in the 36-code registry
 2. EXCLUDED_BY_PROFILE       -- in the registry but not in the site's resolved allowlist
 3. SOURCE_INVALID            -- source missing / unreadable / empty after frontmatter / bad YAML
 4. BLOCKED                   -- governance blocker: NLLB-assigned model while unapproved (G-02),
                                or (site, family) on the holds list (data/campaigns/holds.yaml)
 5. MANUAL_REVIEW_REJECTED    -- Claude REJECTED and source/profile/protection fingerprints unchanged
 6. FAILED_PRIOR_VALIDATION   -- last attempt failed, attempts >= max_attempts, nothing changed
 7. target-existence / provenance branch:
      absent                  -> MISSING_TRANSLATION
      untrustworthy           -> UNKNOWN_PROVENANCE (13th, backfill-only)
      trustworthy: source sha changed -> SOURCE_CHANGED; profile fp changed -> PROFILE_CHANGED;
                   protection fp changed -> PROTECTION_RULE_CHANGED; TM lineage denylisted ->
                   MODEL_OR_PROMPT_INVALIDATED; else UP_TO_DATE

``reclassify_ledger`` re-evaluates every row of the TC-APT-003 ledger against the live
fingerprints (``src/workers/fingerprints.py``), the current source hashes (tracker), the NLLB
licensing flag, the holds list and the TM lineage denylist, and writes the transitions back
(events included).  G-08 DECIDED: ``config/site_profiles/default.yaml`` is never a fingerprint input.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TRUSTWORTHY_PROVENANCE = frozenset({"RECEIPT_BACKED", "AUDITED_BASELINE"})
DEFAULT_HOLDS_PATH = Path("data/campaigns/holds.yaml")
DEFAULT_LINEAGE_DENYLIST = Path("data/tm/invalidated_lineage.json")
DEFAULT_MAX_ATTEMPTS = 5  # primary_attempts (3) + llm_escalation_attempts (2)
#: Frontmatter scalars that make a body-less page translatable content.
TRANSLATABLE_FM_KEYS = (
    "title",
    "description",
    "summary",
    "seoTitle",
    "subtitle",
    "linkTitle",
    "keywords",
    "corporate_header",
)


@dataclass(frozen=True)
class Verdict:
    state: str
    reason_code: str


@dataclass
class CellFacts:
    """Everything the algorithm needs about one cell -- content-free."""

    target_lang: str
    known_langs: frozenset[str]
    profile_langs: frozenset[str]
    site_id: str
    family: str = ""
    source_exists: bool = True
    source_readable: bool = True
    source_nonempty: bool = True
    source_yaml_ok: bool = True
    assigned_model: str | None = None
    nllb_approved: bool = False
    on_hold: bool = False
    review_result: str = "NOT_REQUIRED"  # PENDING | APPROVED | REJECTED | NOT_REQUIRED
    review_source_sha256: str | None = None
    review_profile_fp: str | None = None
    review_protection_fp: str | None = None
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    last_attempt_failed: bool = False
    target_exists: bool = False
    provenance_kind: str = "UNKNOWN"
    provenance_source_sha256: str | None = None
    provenance_profile_fp: str | None = None
    provenance_protection_fp: str | None = None
    current_source_sha256: str = ""
    current_profile_fp: str = ""
    current_protection_fp: str = ""
    tm_lineage_config_fp: str | None = None
    tm_lineage_model_id: str | None = None
    lineage_denylist: frozenset[str] = field(default_factory=frozenset)


def _is_nllb(model_id: str | None) -> bool:
    return bool(model_id) and str(model_id).lower().startswith("nllb")


def classify(f: CellFacts) -> Verdict:
    """Plan section 7.2 precedence; pure and deterministic."""
    if f.target_lang not in f.known_langs:
        return Verdict("UNSUPPORTED_LANGUAGE", "lang_not_in_registry")
    if f.target_lang not in f.profile_langs:
        return Verdict("EXCLUDED_BY_PROFILE", "locale_not_in_profile_allowlist")
    if not f.source_exists:
        return Verdict("SOURCE_INVALID", "source_missing")
    if not f.source_readable:
        return Verdict("SOURCE_INVALID", "source_unreadable")
    if not f.source_yaml_ok:
        return Verdict("SOURCE_INVALID", "frontmatter_yaml_invalid")
    if not f.source_nonempty:
        return Verdict("SOURCE_INVALID", "empty_after_frontmatter")
    if _is_nllb(f.assigned_model) and not f.nllb_approved:
        return Verdict("BLOCKED", "nllb_licensing_not_approved")
    if f.on_hold:
        return Verdict("BLOCKED", "governance_hold")
    fps_unchanged_since_review = (
        f.review_source_sha256 == f.current_source_sha256
        and f.review_profile_fp == f.current_profile_fp
        and f.review_protection_fp == f.current_protection_fp
    )
    if f.review_result == "REJECTED" and fps_unchanged_since_review:
        return Verdict("MANUAL_REVIEW_REJECTED", "claude_rejected_unchanged")
    if (
        f.last_attempt_failed
        and f.attempts >= f.max_attempts
        and fps_unchanged_since_review_or_unknown(f)
    ):
        return Verdict("FAILED_PRIOR_VALIDATION", "max_attempts_exhausted")
    if not f.target_exists:
        return Verdict("MISSING_TRANSLATION", "target_absent")
    if f.provenance_kind not in TRUSTWORTHY_PROVENANCE:
        return Verdict("UNKNOWN_PROVENANCE", "no_trustworthy_provenance")
    if f.provenance_source_sha256 != f.current_source_sha256:
        return Verdict("SOURCE_CHANGED", "source_sha256_differs_from_provenance")
    if f.provenance_profile_fp and f.provenance_profile_fp != f.current_profile_fp:
        return Verdict("PROFILE_CHANGED", "profile_fingerprint_differs")
    if f.provenance_protection_fp and f.provenance_protection_fp != f.current_protection_fp:
        return Verdict("PROTECTION_RULE_CHANGED", "protection_fingerprint_differs")
    if (f.tm_lineage_config_fp and f.tm_lineage_config_fp in f.lineage_denylist) or (
        f.tm_lineage_model_id and f.tm_lineage_model_id in f.lineage_denylist
    ):
        return Verdict("MODEL_OR_PROMPT_INVALIDATED", "tm_lineage_denylisted")
    return Verdict("UP_TO_DATE", "provenance_current")


def fps_unchanged_since_review_or_unknown(f: CellFacts) -> bool:
    """FAILED_PRIOR_VALIDATION only holds while nothing changed; an unknown baseline counts as unchanged."""
    if f.review_source_sha256 is None and f.review_profile_fp is None:
        return True
    return (
        f.review_source_sha256 == f.current_source_sha256
        and f.review_profile_fp == f.current_profile_fp
        and f.review_protection_fp == f.current_protection_fp
    )


# --------------------------------------------------------------------------- inputs
def load_holds(path: Path = DEFAULT_HOLDS_PATH) -> set[tuple[str, str]]:
    """``{holds: [{site_id, family?, reason}]}`` -> {(site_id, family or '*')}."""
    if not path.is_file():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: set[tuple[str, str]] = set()
    for item in data.get("holds") or []:
        out.add((str(item.get("site_id", "")), str(item.get("family") or "*")))
    return out


def is_on_hold(holds: set[tuple[str, str]], site_id: str, family: str) -> bool:
    return (site_id, "*") in holds or (site_id, family) in holds


def load_lineage_denylist(path: Path = DEFAULT_LINEAGE_DENYLIST) -> frozenset[str]:
    """``{"denylist": [{"fingerprint"|"model_id": ..., "reason": ...}]}`` or a flat list."""
    if not path.is_file():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("denylist", data) if isinstance(data, dict) else data
    out: set[str] = set()
    for item in items or []:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict):
            for key in ("fingerprint", "config_fingerprint", "model_id"):
                if item.get(key):
                    out.add(str(item[key]))
    return frozenset(out)


def source_validity(path: Path) -> dict[str, bool]:
    """Cheap structural checks for state 3 (plan 7.2)."""
    if not path.is_file():
        return {
            "source_exists": False,
            "source_readable": False,
            "source_nonempty": False,
            "source_yaml_ok": False,
        }
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            "source_exists": True,
            "source_readable": False,
            "source_nonempty": False,
            "source_yaml_ok": False,
        }
    yaml_ok = True
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                yaml.safe_load(parts[1])
            except yaml.YAMLError:
                yaml_ok = False
            body = parts[2]
        else:
            yaml_ok = False
    # A frontmatter-only page (blog section _index.md, archive.md) still carries translatable
    # fields; "empty after frontmatter strip" (plan 7.2) means NO body AND NO translatable
    # frontmatter scalar -- otherwise section indexes would wrongly become SOURCE_INVALID.
    translatable_fm = False
    if text.startswith("---") and yaml_ok:
        try:
            fm = yaml.safe_load(text.split("---", 2)[1]) or {}
            translatable_fm = any(
                isinstance(fm.get(k), str) and fm.get(k).strip() for k in TRANSLATABLE_FM_KEYS
            )
        except (yaml.YAMLError, AttributeError, IndexError):
            translatable_fm = False
    return {
        "source_exists": True,
        "source_readable": True,
        "source_nonempty": bool(body.strip()) or translatable_fm,
        "source_yaml_ok": yaml_ok,
    }


# --------------------------------------------------------------------------- ledger sweep
def facts_from_row(
    row: dict[str, Any],
    *,
    known_langs: frozenset[str],
    profile_langs: frozenset[str],
    current_source_sha256: str,
    current_profile_fp: str,
    current_protection_fp: str,
    validity: dict[str, bool],
    holds: set[tuple[str, str]],
    lineage_denylist: frozenset[str],
    nllb_approved: bool,
    assigned_model: str | None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> CellFacts:
    vr = row.get("validation_results")
    last_failed = False
    if vr:
        try:
            parsed = json.loads(vr) if isinstance(vr, str) else vr
            last_failed = bool(parsed.get("failed")) if isinstance(parsed, dict) else False
        except (ValueError, AttributeError):
            last_failed = False
    return CellFacts(
        target_lang=row["target_lang"],
        known_langs=known_langs,
        profile_langs=profile_langs,
        site_id=row["site_id"],
        family=row.get("family", ""),
        **validity,
        assigned_model=assigned_model,
        nllb_approved=nllb_approved,
        on_hold=is_on_hold(holds, row["site_id"], row.get("family", "")),
        review_result=row.get("claude_review_result") or "NOT_REQUIRED",
        review_source_sha256=row.get("provenance_source_sha256")
        if row.get("claude_review_result") == "REJECTED"
        else None,
        review_profile_fp=row.get("provenance_profile_fp")
        if row.get("claude_review_result") == "REJECTED"
        else None,
        review_protection_fp=row.get("provenance_protection_fp")
        if row.get("claude_review_result") == "REJECTED"
        else None,
        attempts=int(row.get("attempts") or 0),
        max_attempts=max_attempts,
        last_attempt_failed=last_failed,
        target_exists=bool(row.get("target_exists")),
        provenance_kind=row.get("provenance_kind") or "UNKNOWN",
        provenance_source_sha256=row.get("provenance_source_sha256"),
        provenance_profile_fp=row.get("provenance_profile_fp"),
        provenance_protection_fp=row.get("provenance_protection_fp"),
        current_source_sha256=current_source_sha256,
        current_profile_fp=current_profile_fp,
        current_protection_fp=current_protection_fp,
        tm_lineage_config_fp=row.get("tm_lineage_config_fp"),
        tm_lineage_model_id=row.get("tm_lineage_model_id"),
        lineage_denylist=lineage_denylist,
    )


def reclassify_ledger(
    ledger: Any,
    *,
    content_repo: Path,
    profiles: dict[str, Any],
    translator_repo: Path,
    known_langs: frozenset[str],
    nllb_approved: bool,
    holds_path: Path = DEFAULT_HOLDS_PATH,
    denylist_path: Path = DEFAULT_LINEAGE_DENYLIST,
    assigned_model: str | None = "m2m100_418m",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    site_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-evaluate every ledger row; write transitions (unless dry_run). Returns a summary."""
    from src.utils.content_hash import compute_file_hash
    from src.workers.fingerprints import site_fingerprints

    holds = load_holds(holds_path)
    denylist = load_lineage_denylist(denylist_path)
    summary: dict[str, Any] = {
        "rows": 0,
        "changed": 0,
        "transitions": {},
        "states": {},
        "dry_run": dry_run,
    }
    fp_cache: dict[str, dict[str, str]] = {}
    source_cache: dict[str, tuple[str, dict[str, bool]]] = {}
    updates: list[dict[str, Any]] = []
    for site_id, profile in profiles.items():
        if site_ids and site_id not in site_ids:
            continue
        fps = fp_cache.setdefault(site_id, site_fingerprints(profile, translator_repo))
        profile_langs = frozenset(str(x) for x in profile.target_langs)
        for row in ledger.query(site_id=site_id):
            summary["rows"] += 1
            src_rel = row["source_path"]
            if src_rel not in source_cache:
                path = content_repo / src_rel
                validity = source_validity(path)
                sha = (
                    compute_file_hash(path, "sha256")
                    if validity["source_readable"]
                    else row["source_sha256"]
                )
                source_cache[src_rel] = (sha, validity)
            sha, validity = source_cache[src_rel]
            facts = facts_from_row(
                row,
                known_langs=known_langs,
                profile_langs=profile_langs,
                current_source_sha256=sha,
                current_profile_fp=fps["profile_fingerprint"],
                current_protection_fp=fps["protection_fingerprint"],
                validity=validity,
                holds=holds,
                lineage_denylist=denylist,
                nllb_approved=nllb_approved,
                assigned_model=assigned_model,
                max_attempts=max_attempts,
            )
            verdict = classify(facts)
            summary["states"][verdict.state] = summary["states"].get(verdict.state, 0) + 1
            changed = (
                verdict.state != row["eligibility_state"]
                or verdict.reason_code != row["eligibility_reason_code"]
                or sha != row["source_sha256"]
                or fps["profile_fingerprint"] != row["profile_fingerprint"]
                or fps["protection_fingerprint"] != row["protection_fingerprint"]
            )
            if changed:
                key = f"{row['eligibility_state']}->{verdict.state}"
                summary["transitions"][key] = summary["transitions"].get(key, 0) + 1
                summary["changed"] += 1
                if not dry_run:
                    updates.append(
                        {
                            **row,
                            "eligibility_state": verdict.state,
                            "eligibility_reason_code": verdict.reason_code,
                            "source_sha256": sha,
                            "profile_fingerprint": fps["profile_fingerprint"],
                            "protection_fingerprint": fps["protection_fingerprint"],
                        }
                    )
    if updates:
        for u in updates:
            u.pop("created_at", None)
            u.pop("updated_at", None)
        ledger.bulk_upsert(updates, reason="TC-APT-007 reclassify_ledger")
    return summary


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone

    from scripts.campaign.build_campaign_manifest import (
        IN_SCOPE_SITES,
        load_known_language_codes,
        load_profiles,
    )
    from src.utils.atomic_write import atomic_write
    from src.utils.config_loader import get_global_config
    from src.utils.model_licensing import nllb_production_approved
    from src.workers.work_ledger import DEFAULT_LEDGER_PATH, WorkLedger

    parser = argparse.ArgumentParser(description="TC-APT-007 eligibility reclassification")
    parser.add_argument(
        "--content-repo", type=Path, default=Path("D:/onedrive/Documents/GitHub/aspose.org")
    )
    parser.add_argument("--translator-repo", type=Path, default=Path.cwd())
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-output", type=Path, default=None)
    args = parser.parse_args(argv)

    translator_repo = args.translator_repo.resolve()
    content_repo = args.content_repo.resolve()
    profiles = load_profiles(translator_repo, content_repo, args.sites or IN_SCOPE_SITES)
    known = frozenset(load_known_language_codes(translator_repo))
    nllb_ok = nllb_production_approved(get_global_config())
    with WorkLedger(args.ledger) as ledger:
        summary = reclassify_ledger(
            ledger,
            content_repo=content_repo,
            profiles=profiles,
            translator_repo=translator_repo,
            known_langs=known,
            nllb_approved=nllb_ok,
            site_ids=args.sites,
            dry_run=args.dry_run,
        )
        summary["final_states"] = ledger.counts_by_state()
    summary["at"] = datetime.now(timezone.utc).isoformat()
    out = args.summary_output or Path(
        f"data/campaigns/eligibility_reclassify_{'dry' if args.dry_run else 'live'}.json"
    )
    atomic_write(path=out, content=json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "final_states"}, indent=2))
    print("final_states", json.dumps(summary["final_states"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
