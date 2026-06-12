"""
TC-RBTW-005/006/010: Controlled Profile Test Runner
====================================================
Level 0: Inventory all site profiles (no translation)
Level 1: Missing/stale candidate discovery, dry-run only

Usage:
    python scripts/controlled_profile_test.py inventory
    python scripts/controlled_profile_test.py candidates --all-profiles --dry-run
    python scripts/controlled_profile_test.py candidates --profile golden-test --dry-run

Rules:
- Do NOT write translated content.
- Do NOT modify production files.
- Do NOT perform full-drive scans.
- Classify every profile, even if paths are unresolvable.
- Use null/UNKNOWN rather than fabricating values.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not available. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

PROFILES_DIR = PROJECT_ROOT / "config" / "site_profiles"
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence" / "rbtw"

# Profiles excluded from production metrics (test/fixture/canary)
EXCLUDED_PREFIXES = (
    "blog-test",
    "products-test",
    "golden-test",
    "e2e-reference",
    "stage-b-canary",
    "ws5-test",
    "nested-list-test",
    "realworld",
    "example",
    "default",
)


def _load_profile(path: Path) -> dict:
    """Load a site profile YAML file safely."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        return {"_load_error": str(e)}


def _classify_profile(site_id: str) -> str:
    """Classify a profile as production, test, fixture, canary, or unknown."""
    sid = site_id.lower()
    if any(sid.startswith(p) for p in EXCLUDED_PREFIXES):
        if "canary" in sid:
            return "canary"
        if "test" in sid or "golden" in sid or "fixture" in sid:
            return "test"
        if "realworld" in sid:
            return "fixture"
        if "example" in sid or sid == "default":
            return "example"
        return "test"
    if any(x in sid for x in (".net", ".org", ".com")):
        return "production"
    return "unknown"


def _expand_env(value: str) -> str:
    """Expand environment variables in path strings."""
    return os.path.expandvars(os.path.expanduser(value))


def _resolve_content_roots(roots_raw) -> list[dict]:
    """Resolve content_roots entries, noting which are accessible."""
    results = []
    if not roots_raw:
        return results
    if isinstance(roots_raw, str):
        roots_raw = [roots_raw]
    for raw in roots_raw:
        expanded = _expand_env(str(raw))
        p = Path(expanded)
        results.append(
            {
                "raw": raw,
                "expanded": expanded,
                "exists": p.exists(),
                "is_dir": p.is_dir() if p.exists() else False,
            }
        )
    return results


def cmd_inventory(args) -> int:
    """L0: Enumerate all site profiles and print inventory table."""
    profile_files = sorted(PROFILES_DIR.glob("*.yaml"))
    if not profile_files:
        print(f"ERROR: No profiles found in {PROFILES_DIR}", file=sys.stderr)
        return 1

    rows = []
    errors = []

    for pf in profile_files:
        data = _load_profile(pf)
        if "_load_error" in data:
            errors.append({"file": pf.name, "error": data["_load_error"]})
            continue

        site_id = data.get("site_id", pf.stem)
        roots_raw = data.get("content_roots", [])
        roots = _resolve_content_roots(roots_raw)
        target_langs = data.get("target_langs", [])
        source_lang = data.get("default_source_lang", "en")
        default_model = data.get("default_model", None)
        classification = _classify_profile(site_id)

        # Parse website/section/family/platform from site_id pattern
        # Pattern: section.website.tld.family (e.g. docs.aspose.net.words)
        parts = site_id.split(".")
        website = None
        section = None
        family = None
        if len(parts) >= 3:
            section = parts[0]
            tld = parts[-1] if len(parts) > 2 else None
            # website is middle parts + tld
            website = ".".join(parts[1:]) if len(parts) >= 2 else None
            # family is last part if it's not a TLD-like short string
            if len(parts) >= 4 and len(parts[-1]) > 3:
                family = parts[-1]
                website = ".".join(parts[1:-1])

        roots_resolvable = any(r["exists"] for r in roots)
        roots_status = "OK" if roots_resolvable else ("MISSING" if roots else "NONE")

        blocking_errors = []
        if not roots:
            blocking_errors.append("no_content_roots")
        elif not roots_resolvable:
            blocking_errors.append("content_roots_not_found_locally")
        if "_load_error" in data:
            blocking_errors.append(f"yaml_error: {data['_load_error']}")

        rows.append(
            {
                "profile_file": pf.name,
                "site_id": site_id,
                "classification": classification,
                "source_lang": source_lang,
                "target_langs_count": len(target_langs),
                "target_langs": target_langs,
                "default_model": default_model,
                "website": website,
                "section": section,
                "family": family,
                "roots_count": len(roots),
                "roots_resolvable": roots_resolvable,
                "roots_status": roots_status,
                "roots": roots,
                "blocking_errors": blocking_errors,
            }
        )

    # Print table
    print(f"\n{'=' * 100}")
    print(f"SITE PROFILE INVENTORY  — {len(rows)} profiles found in {PROFILES_DIR.name}/")
    print(f"{'=' * 100}")
    header = f"{'Profile':<42} {'Class':<12} {'Src':<5} {'Tgts':<5} {'Roots':<8} {'Status'}"
    print(header)
    print("-" * 100)
    for r in rows:
        status = "OK" if not r["blocking_errors"] else f"BLOCKED({','.join(r['blocking_errors'])})"
        print(
            f"  {r['site_id']:<40} {r['classification']:<12} "
            f"{r['source_lang']:<5} {r['target_langs_count']:<5} "
            f"{r['roots_count']:<8} {status}"
        )

    if errors:
        print(f"\nLOAD ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e['file']}: {e['error']}")

    # Counts by classification
    from collections import Counter

    cls_counts = Counter(r["classification"] for r in rows)
    print(f"\nBy classification: {dict(cls_counts)}")
    print(f"Resolvable: {sum(1 for r in rows if r['roots_resolvable'])}/{len(rows)}")
    print(f"Blocked: {sum(1 for r in rows if r['blocking_errors'])}/{len(rows)}")

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / "profile_inventory.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "profiles_dir": str(PROFILES_DIR),
                "total_profiles": len(rows),
                "load_errors": len(errors),
                "profiles": rows,
                "errors": errors,
                "classification_counts": dict(cls_counts),
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nEvidence written: {out}")
    return 0


def _count_en_files(root: Path) -> list[Path]:
    """Find English source markdown/html files in a content root."""
    en_files = []
    if not root.exists():
        return en_files
    # Pattern: look for .md/.html files that are NOT in a lang-specific subdirectory
    # Hugo convention: files directly in content/ or in section/ dirs (not /<lang>/ subdirs)
    # We look for *.md and *.html, skipping paths that are under a known lang folder
    known_langs = {
        "ar",
        "bg",
        "ca",
        "cs",
        "da",
        "de",
        "el",
        "es",
        "fa",
        "fi",
        "fr",
        "he",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "vi",
        "zh",
    }
    try:
        for f in root.rglob("*.md"):
            # Skip if any parent dir is a 2-char lang code
            parts = f.relative_to(root).parts
            if any(p in known_langs for p in parts[:-1]):
                continue
            en_files.append(f)
    except PermissionError:
        pass
    return en_files


def _count_translated_files(root: Path, lang: str, en_files: list[Path]) -> dict:
    """Count translated versions of english files for a target lang."""
    lang_root = root / lang
    missing = 0
    present = 0
    if not lang_root.exists():
        # All missing
        return {"missing": len(en_files), "present": 0, "lang_dir_exists": False}
    for en_f in en_files:
        # Compute relative path from content root
        rel = en_f.relative_to(root)
        target = lang_root / rel
        if target.exists():
            present += 1
        else:
            missing += 1
    return {"missing": missing, "present": present, "lang_dir_exists": True}


def cmd_candidates(args) -> int:
    """L1: Dry-run missing/stale detection for all resolvable profiles."""
    profile_files = sorted(PROFILES_DIR.glob("*.yaml"))
    if not profile_files:
        print(f"ERROR: No profiles found in {PROFILES_DIR}", file=sys.stderr)
        return 1

    results = []
    timeout_per_profile = 60  # seconds max per profile

    for pf in profile_files:
        data = _load_profile(pf)
        if "_load_error" in data:
            results.append(
                {
                    "site_id": pf.stem,
                    "status": "FAIL",
                    "reason": f"yaml_error: {data['_load_error']}",
                }
            )
            continue

        site_id = data.get("site_id", pf.stem)

        # Filter by profile if specified
        if args.profile and site_id != args.profile:
            continue

        roots_raw = data.get("content_roots", [])
        roots = _resolve_content_roots(roots_raw)
        target_langs = data.get("target_langs", [])
        source_lang = data.get("default_source_lang", "en")

        resolvable_roots = [r for r in roots if r["exists"] and r["is_dir"]]

        if not resolvable_roots:
            results.append(
                {
                    "site_id": site_id,
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "content_roots_not_found_locally",
                    "roots_raw": [r["raw"] for r in roots],
                }
            )
            continue

        profile_result = {
            "site_id": site_id,
            "status": "PASS",
            "source_lang": source_lang,
            "target_langs": target_langs,
            "pages_total_en": 0,
            "translations_missing": 0,
            "translations_present": 0,
            "by_lang": {},
            "resolvable_roots": len(resolvable_roots),
            "stale_detection_method": "path_existence_only",
            "stale_detection_note": (
                "mtime-based stale detection not run in dry-run scan; "
                "presence/absence used only to avoid OneDrive mtime reliability issues"
            ),
        }

        t0 = time.time()
        for root_info in resolvable_roots:
            root = Path(root_info["expanded"])
            if time.time() - t0 > timeout_per_profile:
                profile_result["status"] = "PARTIAL"
                profile_result["timeout_note"] = f"Timed out after {timeout_per_profile}s"
                break

            try:
                en_files = _count_en_files(root)
                profile_result["pages_total_en"] += len(en_files)

                for lang in target_langs[:10]:  # cap at 10 langs for speed in dry-run
                    counts = _count_translated_files(root, lang, en_files)
                    prev = profile_result["by_lang"].get(lang, {"missing": 0, "present": 0})
                    profile_result["by_lang"][lang] = {
                        "missing": prev["missing"] + counts["missing"],
                        "present": prev["present"] + counts["present"],
                        "lang_dir_exists": counts["lang_dir_exists"],
                    }
                    profile_result["translations_missing"] += counts["missing"]
                    profile_result["translations_present"] += counts["present"]

                if len(target_langs) > 10:
                    profile_result["by_lang_note"] = (
                        f"Only first 10 of {len(target_langs)} target langs scanned in dry-run"
                    )
            except Exception as e:
                profile_result["status"] = "PARTIAL"
                profile_result["scan_error"] = str(e)

        results.append(profile_result)
        status_str = profile_result["status"]
        en_ct = profile_result.get("pages_total_en", "?")
        miss_ct = profile_result.get("translations_missing", "?")
        print(f"  {site_id:<42} {status_str:<10} en_files={en_ct} missing={miss_ct}")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"CANDIDATE DISCOVERY SUMMARY — {len(results)} profiles processed")
    pass_ct = sum(1 for r in results if r.get("status") == "PASS")
    skip_ct = sum(1 for r in results if r.get("status") == "SKIPPED_WITH_REASON")
    fail_ct = sum(1 for r in results if r.get("status") == "FAIL")
    partial_ct = sum(1 for r in results if r.get("status") == "PARTIAL")
    print(f"  PASS: {pass_ct}, PARTIAL: {partial_ct}, SKIPPED: {skip_ct}, FAIL: {fail_ct}")

    total_en = sum(r.get("pages_total_en", 0) for r in results)
    total_missing = sum(r.get("translations_missing", 0) for r in results)
    print(f"  Total EN files across all resolvable profiles: {total_en}")
    print(f"  Total missing translations (first 10 langs): {total_missing}")

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / "candidate_discovery.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": True,
                "mode": "path_existence_check",
                "total_profiles": len(results),
                "pass": pass_ct,
                "partial": partial_ct,
                "skipped": skip_ct,
                "fail": fail_ct,
                "total_en_files": total_en,
                "total_missing_translations": total_missing,
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nEvidence written: {out}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Controlled Profile Test Runner (L0=inventory, L1=candidates)"
    )
    sub = parser.add_subparsers(dest="command")

    inv_p = sub.add_parser("inventory", help="L0: Enumerate all site profiles")
    inv_p.set_defaults(func=cmd_inventory)

    cand_p = sub.add_parser("candidates", help="L1: Dry-run missing/stale detection")
    cand_p.add_argument("--all-profiles", action="store_true")
    cand_p.add_argument("--profile", help="Run for a single profile by site_id")
    cand_p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run (default; never writes translated output)",
    )
    cand_p.set_defaults(func=cmd_candidates)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
