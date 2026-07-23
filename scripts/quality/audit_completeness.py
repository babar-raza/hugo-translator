"""
Tier-3 Completeness Audit — prose-line and code-block ratio comparison.

Compares each translated file against its English source to detect:
  content_drift     — TR prose < 80% of EN prose lines (≥10 EN prose lines)
  empty_body        — TR prose < 20% of EN prose lines (≥5 EN prose lines)
  code_fence_dropped — TR has fewer code blocks than EN (cross-check with T1)

Output: data/audit/audit_completeness.jsonl  (one JSON line per affected file)

TC-AUD-003 implementation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJ_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import iter_locale_pairs  # noqa: E402

_CONFIG = ConfigService(_PROJ_ROOT / "config")
# Durable-fix consolidation: was a hardcoded 5-site list (TC-AUD-007) that
# listed blog.aspose.org in SITES but had NO file-suffix-scheme branch at
# all -- silently producing zero rows for it (same bug class as
# audit_all_content.py, just never noticed here). Now registry-driven via
# ConfigService.list_sites, covering every real production site profile.
SITES = _CONFIG.list_sites(autonomous_only=True)

PRIORITY: dict[str, int] = {
    "empty_body": 1,
    "content_drift": 2,
    "code_fence_dropped": 2,
}

_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def _get_body(content: str) -> str:
    m = _FM_RE.match(content)
    return content[m.end():] if m else content


def count_prose_lines(body: str) -> int:
    """Count non-blank, non-code-block, non-heading lines."""
    in_code = False
    count = 0
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("|"):
            continue  # table rows not counted as prose
        if stripped.startswith("{{"):
            continue  # shortcodes
        count += 1
    return count


def count_code_blocks(body: str) -> int:
    """Count opening code fences (``` with optional lang tag)."""
    return sum(
        1
        for line in body.splitlines()
        if re.match(r"^```\S*\s*$", line.strip()) or line.strip() == "```"
    )


def check_file(en_body: str, tr_body: str) -> dict[str, list[int]]:
    """Return detected issues with placeholder unit_indices (always [0])."""
    issues: dict[str, list[int]] = {}

    en_prose = count_prose_lines(en_body)
    tr_prose = count_prose_lines(tr_body)

    if en_prose >= 5 and tr_prose < 0.20 * en_prose:
        issues["empty_body"] = [0]
    elif en_prose >= 10 and tr_prose < 0.80 * en_prose:
        issues["content_drift"] = [0]

    en_fences = count_code_blocks(en_body)
    tr_fences = count_code_blocks(tr_body)
    if en_fences >= 4 and tr_fences < en_fences - 2:
        issues["code_fence_dropped"] = [0]

    return issues


# ---------------------------------------------------------------------------
# Main scan loop
# ---------------------------------------------------------------------------

def scan(
    sites: list[str],
    locales_filter: list[str] | None,
    output_path: Path,
    resume: bool,
) -> None:
    resumed_paths: set[str] = set()
    if resume and output_path.exists():
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    resumed_paths.add(entry.get("file_path", ""))
                except Exception:  # noqa: BLE001
                    pass
        print(f"[resume] Skipping {len(resumed_paths):,} already-processed files")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_mode = "a" if resume else "w"
    total_files = 0
    total_issues = 0
    issue_counts: dict[str, int] = defaultdict(int)

    with output_path.open(out_mode, encoding="utf-8") as out_fh:
        for site in sites:
            try:
                profile = _CONFIG.get_site_profile(site)
            except Exception as e:  # noqa: BLE001
                print(f"  Skipping {site} (profile load failed: {e})")
                continue

            content_root = _CONFIG.resolve_content_root(profile.content_roots[0])
            if not content_root.exists():
                print(f"  Skipping {site} (content root not found: {content_root})")
                continue

            # Registry-driven discovery: works identically for
            # per_language_folders=True and file-suffix (=False) sites.
            all_locales = sorted(profile.target_langs)
            if locales_filter:
                all_locales = [lc for lc in all_locales if lc in locales_filter]

            en_files = []
            seen_en = set()
            pairs_by_en: dict[Path, list[tuple[str, Path]]] = defaultdict(list)
            for en_path, locale, tr_path in iter_locale_pairs(profile, content_root):
                if locale not in all_locales:
                    continue
                pairs_by_en[en_path].append((locale, tr_path))
                if en_path not in seen_en:
                    seen_en.add(en_path)
                    en_files.append(en_path)

            print(
                f"\n{site}: {len(en_files):,} EN files x {len(all_locales)} locales",
                flush=True,
            )

            done = 0
            for en_path in en_files:
                done += 1
                if done % 2000 == 0:
                    print(f"  ... {done}/{len(en_files)} source files", flush=True)

                try:
                    en_content = en_path.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue

                en_body = _get_body(en_content)

                for locale, tr_path in pairs_by_en[en_path]:
                    total_files += 1
                    if not tr_path.exists():
                        continue
                    if str(tr_path) in resumed_paths:
                        continue

                    try:
                        tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        continue

                    tr_body = _get_body(tr_content)
                    detected = check_file(en_body, tr_body)
                    if not detected:
                        continue

                    file_issues = []
                    max_priority = 9
                    for issue_type, unit_indices in detected.items():
                        prio = PRIORITY.get(issue_type, 4)
                        file_issues.append(
                            {
                                "type": issue_type,
                                "unit_indices": unit_indices,
                                "priority": prio,
                            }
                        )
                        max_priority = min(max_priority, prio)
                        issue_counts[issue_type] += 1

                    record = {
                        "file_path": str(tr_path),
                        "en_path": str(en_path),
                        "locale": locale,
                        "site_id": site,
                        "issues": file_issues,
                        "max_priority": max_priority,
                    }
                    out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_issues += 1

    print(f"\n=== Completeness audit complete ({datetime.now().strftime('%H:%M:%S')}) ===")
    print(f"Files scanned: {total_files:,}")
    print(f"Files with issues: {total_issues:,}")
    print("Issue counts:")
    for issue_type, cnt in sorted(issue_counts.items(), key=lambda x: -x[1]):
        prio = PRIORITY.get(issue_type, 4)
        print(f"  P{prio} {issue_type}: {cnt:,}")
    print(f"\nOutput: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tier-3 completeness audit: prose-line and code-fence ratio."
    )
    parser.add_argument("--sites", nargs="+", default=SITES)
    parser.add_argument("--locales", nargs="+", default=None)
    parser.add_argument("--output", default="data/audit/audit_completeness.jsonl")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = _PROJ_ROOT / output_path

    scan(
        sites=args.sites,
        locales_filter=args.locales,
        output_path=output_path,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
