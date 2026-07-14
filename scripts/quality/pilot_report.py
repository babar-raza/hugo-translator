"""TC-HT-011: E2E pilot before/after report.

Walks a pilot temp-directory output tree, locates each translated file's
current aspose.org counterpart (read-only), and runs the TC-HT-007
vendored consumer checks (check_text / check_pair) over each pair.
Aggregates counts by corruption class against the wave-3 ledger baseline.

Usage:
    python scripts/quality/pilot_report.py <pilot_output_dir> <site_content_root> <site_id>

Example:
    python scripts/quality/pilot_report.py /tmp/docs-pilot d:/onedrive/Documents/GitHub/aspose.org/content docs.aspose.org
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_PROJ_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from src.translation_engine.consumer_intake import check_pair, check_text  # noqa: E402

# wave-3 audit_deep_20260712.log ledger (full-site totals, for scale context only)
WAVE3_BASELINE = {
    "description_hallucination": 571,
    "code_fence_dropped": 836,
    "title_prompt_leak": 85,
}


def run(pilot_dir: Path, content_root: Path, site_id: str) -> dict:
    counts = {"F1": 0, "F2": 0, "F3": 0, "R1": 0, "R2": 0, "R3": 0}
    checked = 0
    findings = []

    for md_file in sorted(pilot_dir.rglob("*.md")):
        rel = md_file.relative_to(pilot_dir)  # e.g. de/getting-started/license.md
        checked += 1
        new_text = md_file.read_text(encoding="utf-8", errors="replace")

        text_failures = check_text(new_text, str(rel))
        for f in text_failures:
            code = f.split(" ", 1)[0]
            counts[code] = counts.get(code, 0) + 1
            findings.append((str(rel), f))

        # Locate the current aspose.org counterpart: content/<site>/<rel>
        counterpart = content_root / site_id / rel
        old_text = None
        if counterpart.exists():
            old_text = counterpart.read_text(encoding="utf-8", errors="replace")
        locale = rel.parts[0] if rel.parts else "und"

        pair_failures = check_pair(new_text, old_text, locale)
        for code in pair_failures:
            counts[code] = counts.get(code, 0) + 1
            findings.append((str(rel), code))

    return {"checked": checked, "counts": counts, "findings": findings}


def print_report(site_id: str, result: dict) -> None:
    print(f"\n=== Pilot report: {site_id} ===")
    print(f"Files checked: {result['checked']}")
    print(f"F1/F2/F3 (frontmatter YAML parse) : {result['counts']['F1'] + result['counts']['F2'] + result['counts']['F3']}")
    print(f"R1 (english regression)           : {result['counts']['R1']}")
    print(f"R2 (prompt leak)                  : {result['counts']['R2']}")
    print(f"R3 (fence-count drop)             : {result['counts']['R3']}")
    if result["findings"]:
        print("\nPer-file findings:")
        for rel, code in result["findings"]:
            print(f"  {rel}: {code}")
    else:
        print("\nZero findings across all three corruption classes.")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    pilot_dir = Path(sys.argv[1])
    content_root = Path(sys.argv[2])
    site_id = sys.argv[3]
    result = run(pilot_dir, content_root, site_id)
    print_report(site_id, result)
