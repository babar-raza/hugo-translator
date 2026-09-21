#!/usr/bin/env python
"""VA-02 (TC-APT-105 audit): read-only scan for the duplicate-link defect
shape confirmed live on docs.aspose.org -- an identical markdown link or
bold-wrapped-link construct (``[text](url)`` or ``**[text](url)**``)
appearing twice within the same paragraph, back-to-back or not.

This is a diagnostic tool only: it never modifies a content file, and it
never scans anything unless the caller explicitly names a root directory or
files (no full-repo default). Remediation of any finding is a separate,
human-reviewed action -- file a heal_queue.jsonl ticket per finding, do not
auto-fix from this script.

Usage:
    python scripts/audit/detect_duplicate_link_content.py \\
        --root D:/onedrive/Documents/GitHub/aspose.org/content/docs.aspose.org \\
        --report out.json

    python scripts/audit/detect_duplicate_link_content.py --file a.md b.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Same construct shape as write_gate.py's _INLINE_LINK_RE (VA-03) -- kept as
# an independent constant here rather than imported, since this is a
# standalone read-only diagnostic tool, not part of the write pipeline.
_INLINE_LINK_RE = re.compile(r"\*\*\[[^\]]+\]\([^)]+\)\*\*|\[[^\]]+\]\([^)]+\)")

_LOCALE_SUFFIX_RE = re.compile(r"\.([a-z]{2,3}(?:-[a-z]{2})?)\.md$", re.IGNORECASE)
_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")


def detect_locale(path: Path, root: Path | None) -> str:
    """Best-effort locale detection for this repo's two content-layout
    conventions -- a filename suffix (``index.de.md``) or a locale directory
    segment immediately under the scanned root (``docs.aspose.org/de/...``).

    This is a diagnostic label, not an authoritative classification: on
    ambiguity it returns "unknown" rather than guessing a platform/product
    segment (e.g. "go", "net") is a locale.
    """
    suffix_match = _LOCALE_SUFFIX_RE.search(path.name)
    if suffix_match:
        return suffix_match.group(1).lower()
    if root is not None:
        try:
            rel_parts = path.resolve().relative_to(root.resolve()).parts
        except ValueError:
            rel_parts = ()
        if rel_parts and _LOCALE_SEGMENT_RE.match(rel_parts[0]):
            return rel_parts[0].lower()
    return "unknown"


def find_duplicate_link_matches(text: str) -> list[str]:
    """Return each distinct link/bold-link construct string that appears
    2 or more times within the same paragraph (blank-line-delimited) of
    `text` -- back-to-back or with other content between the occurrences,
    per the confirmed defect shape. A construct repeating across DIFFERENT
    paragraphs (e.g. the same "Installation" link cited in two separate
    sections) is not flagged; that is normal, legitimate content.
    """
    findings: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        seen_once: set[str] = set()
        seen_dup: set[str] = set()
        for match in _INLINE_LINK_RE.finditer(paragraph):
            construct = match.group(0)
            if construct in seen_once:
                seen_dup.add(construct)
            else:
                seen_once.add(construct)
        findings.extend(sorted(seen_dup))
    return findings


def scan_file(path: Path, root: Path | None) -> list[dict[str, str]]:
    """Read-only: return one {file, locale, match} dict per duplicate found
    in `path`. Never writes to `path`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    locale = detect_locale(path, root)
    return [
        {"file": str(path), "locale": locale, "match": match}
        for match in find_duplicate_link_matches(text)
    ]


def scan(*, root: Path | None, files: list[Path]) -> list[dict[str, str]]:
    """Read-only scan of `root` (recursive, *.md) and/or explicit `files`.
    Returns an empty list when given nothing to scan -- never defaults to
    scanning the whole repo."""
    targets: list[Path] = list(files)
    if root is not None:
        targets.extend(sorted(root.rglob("*.md")))
    findings: list[dict[str, str]] = []
    for path in targets:
        findings.extend(scan_file(path, root))
    return findings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only scan for the duplicate-link content defect (TC-APT-105). "
            "Reports findings; never modifies content. Remediate via a separate, "
            "human-reviewed heal_queue.jsonl ticket per finding."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Directory to recursively scan for *.md files. Not scanned unless given.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        nargs="*",
        default=[],
        help="Explicit file path(s) to scan, in addition to/instead of --root.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the JSON findings list here. Prints to stdout if omitted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.root is None and not args.file:
        print(
            "No --root or --file given -- nothing to scan (this tool never "
            "defaults to a full-repo scan).",
            file=sys.stderr,
        )
        return 1

    findings = scan(root=args.root, files=args.file)
    payload = json.dumps(findings, indent=2)
    if args.report is not None:
        args.report.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
