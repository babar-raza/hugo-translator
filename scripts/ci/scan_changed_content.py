#!/usr/bin/env python3
"""
CI step: scan changed translated content files for structural defects.

Usage (in CI workflow):
    python scripts/ci/scan_changed_content.py \
        --changed-files "$(git diff --name-only HEAD~1 HEAD)" \
        --content-root D:/onedrive/Documents/GitHub/aspose.net/content \
        --output workspace/runs/scan-ci-$(date +%Y%m%d-%H%M%S).json

Exit codes:
    0 = no structural errors in changed files
    1 = structural errors found (blocks merge/push)
    2 = unexpected error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path so we can import repair_translated_content
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from scripts.repair_translated_content import (
        KNOWN_FAILING,
        SEVERITY_ERROR,
        scan_changed_files,
    )
except ImportError as e:
    print(f"ERROR: Cannot import repair_translated_content: {e}", file=sys.stderr)
    sys.exit(2)


# Issue kinds that block CI (high-confidence real failures)
BLOCKING_KINDS = {
    "yaml_parse_failure",
    "missing_closing_delimiter",
    "translated_yaml_key",
    "url_corruption",
    "block_scalar_indent_failure",
    "orphan_closing_shortcode",
    "type_drift",
    "passthrough_field_changed",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI scan of changed translated content files"
    )
    parser.add_argument(
        "--changed-files",
        help="Newline/space separated list of changed file paths",
    )
    parser.add_argument(
        "--changed-files-from",
        type=Path,
        help="File containing list of changed paths (one per line)",
    )
    parser.add_argument(
        "--content-root",
        type=Path,
        default=None,
        help="Content root directory for relative path resolution",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON results to this file",
    )
    parser.add_argument(
        "--allow-kinds",
        nargs="*",
        default=[],
        help="Issue kinds to allow (non-blocking) even if they match BLOCKING_KINDS",
    )
    args = parser.parse_args()

    # Build list of changed files
    paths: list[str] = []

    if args.changed_files:
        # Split on newlines and spaces
        for p in args.changed_files.replace("\n", " ").split():
            p = p.strip()
            if p:
                # Resolve relative to content_root if provided
                if args.content_root and not Path(p).is_absolute():
                    resolved = args.content_root / p
                    if resolved.exists():
                        paths.append(str(resolved))
                        continue
                paths.append(p)

    if args.changed_files_from and args.changed_files_from.exists():
        for line in args.changed_files_from.read_text(encoding="utf-8").splitlines():
            p = line.strip()
            if p:
                if args.content_root and not Path(p).is_absolute():
                    resolved = args.content_root / p
                    if resolved.exists():
                        paths.append(str(resolved))
                        continue
                paths.append(p)

    if not paths:
        print("No changed translated files to scan.", file=sys.stderr)
        return 0

    print(f"Scanning {len(paths)} changed file(s)...", file=sys.stderr)

    result = scan_changed_files(
        paths=paths,
        content_root=args.content_root,
        known_failing=KNOWN_FAILING,
    )

    # Write JSON output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Results written to {args.output}", file=sys.stderr)

    # Determine blocking issues
    allowed = set(args.allow_kinds or [])
    blocking_issues = [
        i for i in result.all_issues
        if i.severity == SEVERITY_ERROR
        and i.kind in BLOCKING_KINDS
        and i.kind not in allowed
    ]

    total = len(result.all_issues)
    errors = len(blocking_issues)
    affected = len(set(i.path for i in blocking_issues))

    print(f"\nScan results: {result.total_files_scanned} files checked, {total} issues total, {errors} blocking errors in {affected} files", file=sys.stderr)

    if blocking_issues:
        print("\nBlocking issues found:", file=sys.stderr)
        for issue in blocking_issues[:20]:
            line_str = f":{issue.line}" if issue.line else ""
            print(f"  [{issue.kind}] {issue.path}{line_str}: {issue.message[:100]}", file=sys.stderr)
        if len(blocking_issues) > 20:
            print(f"  ... and {len(blocking_issues) - 20} more", file=sys.stderr)
        return 1

    print("No blocking structural issues found.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
