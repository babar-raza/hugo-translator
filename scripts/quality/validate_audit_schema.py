"""
Validate audit JSONL files conform to the expected schema.

Required top-level fields: file_path, en_path, locale, site_id, issues, max_priority
Required per-issue fields:  type, unit_indices, priority

Exits 0 if all files are valid, 1 if any malformed entries are found.

TC-AUD-006 implementation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJ_ROOT = _SCRIPT_DIR.parent.parent

REQUIRED_TOP = {"file_path", "en_path", "locale", "site_id", "issues", "max_priority"}
REQUIRED_ISSUE = {"type", "unit_indices", "priority"}


def validate_file(path: Path) -> int:
    """Return number of invalid lines found."""
    errors = 0
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"  ERROR {path.name}:{lineno}: JSON parse error: {exc}")
                errors += 1
                continue

            missing_top = REQUIRED_TOP - entry.keys()
            if missing_top:
                print(f"  ERROR {path.name}:{lineno}: missing top-level fields: {missing_top}")
                errors += 1
                continue

            if not isinstance(entry["issues"], list):
                print(f"  ERROR {path.name}:{lineno}: 'issues' must be a list")
                errors += 1
                continue

            for issue in entry["issues"]:
                if not isinstance(issue, dict):
                    print(f"  ERROR {path.name}:{lineno}: issue entry must be a dict")
                    errors += 1
                    continue
                missing_issue = REQUIRED_ISSUE - issue.keys()
                if missing_issue:
                    print(f"  ERROR {path.name}:{lineno}: issue missing fields: {missing_issue}")
                    errors += 1

            if not isinstance(entry["max_priority"], int):
                print(
                    f"  ERROR {path.name}:{lineno}: max_priority must be int, got {type(entry['max_priority'])}"
                )
                errors += 1

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate audit JSONL schema.")
    parser.add_argument(
        "files",
        nargs="*",
        help="JSONL files to validate. If omitted, validates all files in data/audit/.",
    )
    args = parser.parse_args()

    if args.files:
        paths = [Path(f) for f in args.files]
    else:
        audit_dir = _PROJ_ROOT / "data" / "audit"
        if not audit_dir.exists():
            print(f"data/audit/ not found at {audit_dir}")
            sys.exit(1)
        paths = sorted(audit_dir.glob("*.jsonl"))
        if not paths:
            print(f"No .jsonl files found in {audit_dir}")
            sys.exit(0)

    total_errors = 0
    for path in paths:
        if not path.exists():
            print(f"  SKIP {path}: not found")
            continue
        errors = validate_file(path)
        if errors:
            print(f"  FAIL {path.name}: {errors} error(s)")
        else:
            print(f"  OK   {path.name}")
        total_errors += errors

    if total_errors:
        print(f"\n{total_errors} total error(s) found.")
        sys.exit(1)
    else:
        print("\nAll files valid.")
        sys.exit(0)


if __name__ == "__main__":
    main()
