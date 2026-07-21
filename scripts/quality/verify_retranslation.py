"""
HT-QUALITY-GATES-001 Phase D: automated, repo-checked-in post-retranslation
verifier. Formalizes the ad-hoc script used earlier this session for the
"TRUE PICTURE" ground-truth check — fixing its own bugs along the way:

- Reads every file as explicit UTF-8 text (a `grep`-based check earlier this
  session silently treated non-ASCII-heavy log files as binary and
  suppressed matching lines — this script never shells out to grep).
- Does NOT flag "empty body" as a defect: family/platform pages on
  products.aspose.org are frontmatter-only (all content lives in YAML
  fields, rendered by a Hugo template) — the original ad-hoc script's
  empty_body check was a false positive on 100% of files for this reason.
- Placeholder-leak detection is brace-optional (PLACEHOLDER_\\d+ with or
  without braces), matching the real brace-stripping failure mode
  confirmed against the actual MT model this session (see
  PlaceholderManager.restore()'s HT-QUALITY-GATES-001 RC2 comment).

Usage:
    python scripts/quality/verify_retranslation.py --queue-file .local/heal_x.jsonl
    python scripts/quality/verify_retranslation.py --queue-file .local/heal_x.jsonl \
        --title-match-threshold 0.90 --report-path reports/verify_x.json

Exit code 0 = all thresholds met. Exit code 1 = regression (title-match rate
below threshold, or any placeholder leak, or any file genuinely missing).
This is meant to run unconditionally as the last step of every retranslation
(canary or full), not as a one-off a human has to remember to invoke.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content\products.aspose.org")

_PLACEHOLDER_RE = re.compile(r"\{?PLACEHOLDER_\d+\}?")


def load_frontmatter(content: str) -> tuple[dict | None, str | None]:
    import yaml

    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", content, re.DOTALL)
    if not m:
        return None, None
    try:
        return yaml.safe_load(m.group(1)), m.group(2)
    except yaml.YAMLError:
        return None, None


def page_to_rel(page: str) -> str:
    page = page.strip()
    return page if page.endswith("_index.md") else f"{page}/_index.md"


def verify(
    queue_entries: list[dict],
    content_root: Path,
) -> dict:
    results = {
        "total": len(queue_entries),
        "file_missing": 0,
        "file_exists": 0,
        "title_checked": 0,
        "title_match": 0,
        "title_mismatch": 0,
        "title_mismatch_detail": [],
        "placeholder_leak": 0,
        "placeholder_leak_detail": [],
        "yaml_parse_fail": 0,
        "yaml_parse_fail_detail": [],
    }

    en_frontmatter_cache: dict[Path, dict | None] = {}

    for entry in queue_entries:
        locale = entry["locale"]
        rel = entry["rel"].replace("\\", "/")
        en_path = content_root / "en" / rel
        tgt_path = content_root / locale / rel

        if en_path not in en_frontmatter_cache:
            if en_path.exists():
                en_content = en_path.read_text(encoding="utf-8", errors="strict")
                en_fm, _ = load_frontmatter(en_content)
            else:
                en_fm = None
            en_frontmatter_cache[en_path] = en_fm
        en_fm = en_frontmatter_cache[en_path]

        if not tgt_path.exists():
            results["file_missing"] += 1
            continue
        results["file_exists"] += 1

        tgt_content = tgt_path.read_text(encoding="utf-8", errors="strict")
        tgt_fm, tgt_body = load_frontmatter(tgt_content)

        if tgt_fm is None:
            results["yaml_parse_fail"] += 1
            results["yaml_parse_fail_detail"].append(f"{rel} / {locale}")
            continue

        en_title = (en_fm or {}).get("title")
        tgt_title = tgt_fm.get("title")
        if isinstance(en_title, str) and isinstance(tgt_title, str):
            results["title_checked"] += 1
            if tgt_title.strip() == en_title.strip():
                results["title_match"] += 1
            else:
                results["title_mismatch"] += 1
                results["title_mismatch_detail"].append(
                    f"{rel} / {locale}: EN={en_title!r} -> GOT={tgt_title!r}"
                )

        fm_blob = json.dumps(tgt_fm, ensure_ascii=False)
        if _PLACEHOLDER_RE.search(fm_blob) or _PLACEHOLDER_RE.search(tgt_body or ""):
            results["placeholder_leak"] += 1
            results["placeholder_leak_detail"].append(f"{rel} / {locale}")

    title_rate = (
        results["title_match"] / results["title_checked"] if results["title_checked"] else 1.0
    )
    results["title_match_rate"] = title_rate
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue-file", required=True, help="JSONL queue file (site/locale/rel per line)")
    ap.add_argument("--content-root", default=str(DEFAULT_CONTENT_ROOT))
    ap.add_argument("--title-match-threshold", type=float, default=0.90)
    ap.add_argument("--allow-missing", type=int, default=0, help="Max files allowed missing")
    ap.add_argument("--report-path", default=None)
    args = ap.parse_args()

    queue_entries = []
    with open(args.queue_file, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                queue_entries.append(json.loads(line))

    results = verify(queue_entries, Path(args.content_root))

    print(f"Total queued: {results['total']}")
    print(f"File exists: {results['file_exists']} / missing: {results['file_missing']}")
    print(f"YAML parse failures: {results['yaml_parse_fail']}")
    print(
        f"Title match: {results['title_match']} / {results['title_checked']} "
        f"({results['title_match_rate']:.1%})"
    )
    print(f"Placeholder leaks: {results['placeholder_leak']}")

    if args.report_path:
        Path(args.report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_path).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full report: {args.report_path}")

    passed = (
        results["file_missing"] <= args.allow_missing
        and results["yaml_parse_fail"] == 0
        and results["placeholder_leak"] == 0
        and results["title_match_rate"] >= args.title_match_threshold
    )

    if not passed:
        print("\nVERIFY: FAIL")
        if results["placeholder_leak"] > 0:
            print(f"  - {results['placeholder_leak']} placeholder leak(s) — see placeholder_leak_detail in report")
        if results["title_match_rate"] < args.title_match_threshold:
            print(
                f"  - title match rate {results['title_match_rate']:.1%} below threshold "
                f"{args.title_match_threshold:.1%}"
            )
        if results["file_missing"] > args.allow_missing:
            print(f"  - {results['file_missing']} file(s) missing (allowed: {args.allow_missing})")
        return 1

    print("\nVERIFY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
