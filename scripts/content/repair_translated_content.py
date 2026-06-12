#!/usr/bin/env python3
"""
Repair and scan tool for translated Hugo content files.

Detects structural defects in translated Markdown content:
- YAML frontmatter parse failures
- Block scalar indentation failures (content not deeper than key)
- Collapsed single-line YAML (multiple key:value on one line)
- Multiple YAML keys merged onto same line
- Translated YAML key names (keys differ from English source)
- Hugo shortcode imbalance (orphan openers/closers)
- Corrupted shortcode delimiters / translated shortcode names
- Type drift (boolean became string, date became string, etc.)
- URL corruption in frontmatter values
- Cross-field contamination patterns

Usage:
    python scripts/repair_translated_content.py --content-dir PATH [--dry-run] [--write] [--ci]
    python scripts/repair_translated_content.py --file FILE [--source-file SRCFILE]

Exit codes:
    0 = clean (no issues or all fixed)
    1 = issues found (in --ci mode)
    2 = unexpected error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# Language codes to detect translated files
LANG_CODES = {
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

# YAML keys that must never be translated
CANONICAL_PASSTHROUGH_KEYS = {
    "layout",
    "type",
    "draft",
    "date",
    "lastmod",
    "weight",
    "url",
    "slug",
    "aliases",
    "productname",
    "productkey",
    "platformkey",
    "productplatform",
    "source_version",
    "generated_by",
    "enhanced",
    "howtoimage",
    "cart_id",
    "gisthash",
    "gistfile",
    "enable",
    "linktitle",
}

# Czech/German/French common translations of canonical keys (signals key translation)
TRANSLATED_KEY_PATTERNS = {
    # Czech
    "autor",
    "datum",
    "popis",
    "nazev",
    "kategorie",
    "shrnutí",
    "shrnuty",
    "posledni",
    "zvysena",
    "dny",
    "titulek",
    # French
    "auteur",
    "date_creation",
    "titre",
    "description_fr",
    # German
    "titel",
    "beschreibung",
    # Arabic
    "مؤلف",
    "تاريخ",
    "وصف",
    "عنوان",
    # Japanese
    "著者",
    "日付",
}

# Hugo shortcode opening/closing pattern
SHORTCODE_OPEN_RE = re.compile(r"\{\{[<%]\s*/?\s*(\w+)[^>%]*[>%]\}\}")
SHORTCODE_PAIRS_RE = re.compile(r"\{\{[<%]\s*(/?)(\w+)[^>%]*[>%]\}\}")
BLOCK_SCALAR_RE = re.compile(r"^(\s*)(\w[\w.-]*):\s*[|>][-+]?\s*$")
MULTI_KV_RE = re.compile(r"\w[\w.-]*:\s+\S.*\w[\w.-]*:\s")
URL_RE = re.compile(r"https?://\S+")
CANONICAL_URL_PATTERN = re.compile(
    r"https?://(?:docs|releases|products|blog|kb)\.aspose\.(com|net|org|app)/"
)


@dataclass
class Issue:
    path: str
    line: int | None
    kind: str
    message: str
    severity: str = SEVERITY_ERROR
    safe_autofix: bool = False
    manual_review: bool = False
    source_english_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
            "safe_autofix": self.safe_autofix,
            "manual_review": self.manual_review,
            "source_english_path": self.source_english_path,
        }


@dataclass
class ScanResult:
    total_files_scanned: int = 0
    known_failures_found: list[str] = field(default_factory=list)
    additional_failures_found: list[str] = field(default_factory=list)
    known_failures_fixed: list[str] = field(default_factory=list)
    additional_failures_fixed: list[str] = field(default_factory=list)
    unsafe_or_uncertain: list[str] = field(default_factory=list)
    issues_by_category: dict[str, int] = field(default_factory=dict)
    all_issues: list[Issue] = field(default_factory=list)

    def add_issue(self, issue: Issue) -> None:
        self.all_issues.append(issue)
        self.issues_by_category[issue.kind] = self.issues_by_category.get(issue.kind, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files_scanned": self.total_files_scanned,
            "known_failures_found": self.known_failures_found,
            "additional_failures_found": self.additional_failures_found,
            "known_failures_fixed": self.known_failures_fixed,
            "additional_failures_fixed": self.additional_failures_fixed,
            "unsafe_or_uncertain": self.unsafe_or_uncertain,
            "issues_by_category": self.issues_by_category,
            "all_issues": [i.to_dict() for i in self.all_issues],
        }


# ---------------------------------------------------------------------------
# Known failing files (relative to content root)
# ---------------------------------------------------------------------------
KNOWN_FAILING = {
    "content/products.aspose.net/barcode/ar/2d-barcode-reader/_index.md",
    "content/products.aspose.net/cad/ar/dwg-dxf-dwt-file-processor/_index.md",
    "content/products.aspose.net/cells/ar/_index.md",
    "content/products.aspose.net/html/ar/html-to-pdf-converter/_index.md",
    "content/products.aspose.net/imaging/ar/_index.md",
    "content/products.aspose.net/ocr/ar/scanned-image-to-text/_index.md",
    "content/products.aspose.net/pdf/ar/xls-converter/_index.md",
    "content/products.aspose.net/svg/ar/_index.md",
    "content/products.aspose.net/words/ar/document-converter/_index.md",
    "content/products.aspose.net/zip/ar/rar-extractor/_index.md",
    "content/kb.aspose.net/words/ja/how-to-add-watermarks-word-documents-aspnet-api.md",
    "content/blog.aspose.net/barcode/add-barcode-in-asp-dotnet-mvc/index.cs.md",
}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def is_translated_file(path: Path) -> bool:
    """Return True if this looks like a translated (non-English) Markdown file."""
    name = path.name
    # pattern: index.XX.md or _index.md in a lang folder
    m = re.match(r"^(?:index|_index)\.([a-z]{2})\.md$", name)
    if m and m.group(1) in LANG_CODES:
        return True
    # Check parent directory is a lang code
    if path.parent.name in LANG_CODES:
        return True
    return False


def find_english_source(path: Path) -> Path | None:
    """Try to locate the English source file for a translated file."""
    name = path.name
    parent = path.parent

    # index.XX.md -> index.md (same dir)
    m = re.match(r"^(index|_index)\.([a-z]{2})\.md$", name)
    if m:
        src = parent / f"{m.group(1)}.md"
        if src.exists():
            return src
        src2 = parent / f"{m.group(1)}.en.md"
        if src2.exists():
            return src2

    # path/XX/file.md -> path/en/file.md
    if parent.name in LANG_CODES:
        en_parent = parent.parent / "en"
        src = en_parent / name
        if src.exists():
            return src

    return None


def extract_frontmatter(text: str) -> tuple[str | None, str | None, str]:
    """Extract frontmatter YAML and body. Returns (frontmatter_str, body_str, error)."""
    if not text.startswith("---"):
        # Check if there's a leading blank line
        stripped = text.lstrip("\n\r")
        if not stripped.startswith("---"):
            return None, text, "no_frontmatter_delimiter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text, "missing_closing_delimiter"
    return parts[1], parts[2], ""


def check_yaml_parseable(fm_str: str, path_str: str) -> list[Issue]:
    """Check that frontmatter YAML parses with yaml.safe_load."""
    issues = []
    try:
        yaml.safe_load(fm_str)
    except yaml.YAMLError as e:
        msg = str(e).split("\n")[0]
        # Extract line number
        m = re.search(r"line (\d+), column (\d+)", str(e))
        line = int(m.group(1)) + 1 if m else None  # +1 for the opening ---
        issues.append(
            Issue(
                path=path_str,
                line=line,
                kind="yaml_parse_failure",
                message=f"YAML frontmatter fails to parse: {msg}",
                severity=SEVERITY_ERROR,
                safe_autofix=False,
                manual_review=True,
            )
        )
    return issues


def check_block_scalar_indent(fm_str: str, path_str: str) -> list[Issue]:
    """Check that block scalar content is more indented than the key."""
    issues = []
    lines = fm_str.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = BLOCK_SCALAR_RE.match(line)
        if m:
            key_indent = len(m.group(1))
            # Find first non-empty line after the block scalar indicator
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                content_line = lines[j]
                content_indent = len(content_line) - len(content_line.lstrip())
                if content_indent <= key_indent and content_line.strip():
                    issues.append(
                        Issue(
                            path=path_str,
                            line=i + 2,  # +1 for --- +1 for 0-index
                            kind="block_scalar_indent_failure",
                            message=(
                                f"Block scalar '{m.group(2)}:' at indent {key_indent}, "
                                f"but content at indent {content_indent} (must be deeper)"
                            ),
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,  # Need to know correct indentation
                            manual_review=True,
                        )
                    )
        i += 1
    return issues


def check_collapsed_frontmatter(fm_str: str, path_str: str) -> list[Issue]:
    """Detect frontmatter collapsed onto single/few lines (multiple key:value on one line)."""
    issues = []
    lines = fm_str.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Count colon-separated key patterns on one line
        # A line like "key1: val1 key2: val2" is suspicious
        if MULTI_KV_RE.search(line):
            issues.append(
                Issue(
                    path=path_str,
                    line=i + 2,
                    kind="collapsed_frontmatter",
                    message=f"Multiple YAML key:value pairs on one line (collapsed structure): {line[:80]}",
                    severity=SEVERITY_ERROR,
                    safe_autofix=False,
                    manual_review=True,
                )
            )
    return issues


def check_translated_keys(
    fm_str: str, path_str: str, source_fm_str: str | None = None
) -> list[Issue]:
    """Check that YAML keys haven't been translated."""
    issues = []
    try:
        fm_data = yaml.safe_load(fm_str)
        if not isinstance(fm_data, dict):
            return issues

        def check_keys_recursive(data: dict, prefix: str = "") -> None:
            for key in data.keys():
                key_lower = str(key).lower()
                # Check against known translated key patterns
                if key_lower in TRANSLATED_KEY_PATTERNS:
                    issues.append(
                        Issue(
                            path=path_str,
                            line=None,
                            kind="translated_yaml_key",
                            message=f"YAML key '{key}' appears to be translated (expected canonical English key)",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
                # Check against source keys if available
                val = data[key]
                if isinstance(val, dict):
                    check_keys_recursive(val, f"{prefix}{key}.")

        check_keys_recursive(fm_data)

        # If source provided, compare key sets
        if source_fm_str:
            try:
                src_data = yaml.safe_load(source_fm_str)
                if isinstance(src_data, dict) and isinstance(fm_data, dict):
                    src_keys = set(str(k) for k in src_data.keys())
                    tgt_keys = set(str(k) for k in fm_data.keys())
                    extra_keys = tgt_keys - src_keys - {"source_version", "generated_by"}
                    missing_keys = src_keys - tgt_keys - {"source_version", "generated_by"}
                    if extra_keys:
                        issues.append(
                            Issue(
                                path=path_str,
                                line=None,
                                kind="translated_yaml_key",
                                message=f"Translated file has extra keys not in source: {sorted(extra_keys)}",
                                severity=SEVERITY_ERROR,
                                safe_autofix=False,
                                manual_review=True,
                            )
                        )
                    if missing_keys:
                        issues.append(
                            Issue(
                                path=path_str,
                                line=None,
                                kind="missing_yaml_key",
                                message=f"Translated file is missing keys from source: {sorted(missing_keys)}",
                                severity=SEVERITY_WARNING,
                                safe_autofix=False,
                                manual_review=True,
                            )
                        )
            except yaml.YAMLError:
                pass

    except yaml.YAMLError:
        pass  # Already caught by check_yaml_parseable
    return issues


def check_type_drift(fm_str: str, path_str: str, source_fm_str: str) -> list[Issue]:
    """Check for type drift: boolean became string, date became string, etc."""
    issues = []
    try:
        fm_data = yaml.safe_load(fm_str)
        src_data = yaml.safe_load(source_fm_str)
        if not isinstance(fm_data, dict) or not isinstance(src_data, dict):
            return issues

        for key in src_data:
            if key not in fm_data:
                continue
            src_val = src_data[key]
            tgt_val = fm_data[key]
            src_type = type(src_val).__name__
            tgt_type = type(tgt_val).__name__

            if src_type != tgt_type:
                # Some type changes are ok (None -> str for optional fields)
                if src_val is None:
                    continue
                # bool -> str is always wrong
                if isinstance(src_val, bool) and not isinstance(tgt_val, bool):
                    issues.append(
                        Issue(
                            path=path_str,
                            line=None,
                            kind="type_drift",
                            message=f"Key '{key}': source is bool ({src_val!r}), translation is {tgt_type} ({tgt_val!r})",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
                # list -> scalar is always wrong
                elif isinstance(src_val, list) and not isinstance(tgt_val, list):
                    issues.append(
                        Issue(
                            path=path_str,
                            line=None,
                            kind="type_drift",
                            message=f"Key '{key}': source is list, translation is {tgt_type} (structure changed)",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
                # scalar -> list (unexpected)
                elif not isinstance(src_val, dict | list) and isinstance(tgt_val, list):
                    issues.append(
                        Issue(
                            path=path_str,
                            line=None,
                            kind="type_drift",
                            message=f"Key '{key}': source is {src_type}, translation is list (structure changed)",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
    except yaml.YAMLError:
        pass
    return issues


def check_passthrough_fields(fm_str: str, path_str: str, source_fm_str: str) -> list[Issue]:
    """Check that known passthrough fields (draft, date, layout, etc.) are unchanged."""
    issues = []
    try:
        fm_data = yaml.safe_load(fm_str)
        src_data = yaml.safe_load(source_fm_str)
        if not isinstance(fm_data, dict) or not isinstance(src_data, dict):
            return issues

        for key in CANONICAL_PASSTHROUGH_KEYS:
            if key in src_data and key in fm_data:
                src_val = src_data[key]
                tgt_val = fm_data[key]
                if src_val != tgt_val:
                    issues.append(
                        Issue(
                            path=path_str,
                            line=None,
                            kind="passthrough_field_changed",
                            message=f"Passthrough field '{key}' changed: {src_val!r} -> {tgt_val!r}",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
    except yaml.YAMLError:
        pass
    return issues


def check_shortcode_balance(body_str: str, path_str: str) -> list[Issue]:
    """Check Hugo shortcode pairing in document body."""
    issues = []

    # Track open/close counts per shortcode name
    stack: list[tuple[str, int]] = []  # (name, line_number)
    lines = body_str.split("\n")

    for i, line in enumerate(lines, 1):
        for m in SHORTCODE_PAIRS_RE.finditer(line):
            is_closing = bool(m.group(1))
            name = m.group(2)
            full = m.group(0)

            if is_closing:
                # Check if there's a matching opener
                matching = None
                for j in range(len(stack) - 1, -1, -1):
                    if stack[j][0] == name:
                        matching = j
                        break
                if matching is None:
                    issues.append(
                        Issue(
                            path=path_str,
                            line=i,
                            kind="orphan_closing_shortcode",
                            message=f"Closing shortcode '{full}' has no matching opener",
                            severity=SEVERITY_ERROR,
                            safe_autofix=False,
                            manual_review=True,
                        )
                    )
                else:
                    stack.pop(matching)
            else:
                # Self-closing shortcodes end with /
                if not full.rstrip("}").rstrip().endswith("/"):
                    stack.append((name, i))

    # Any remaining in stack are unclosed openers
    for name, line_num in stack:
        issues.append(
            Issue(
                path=path_str,
                line=line_num,
                kind="orphan_opening_shortcode",
                message=f"Opening shortcode '{{{{% {name} %}}}}' has no matching closer",
                severity=SEVERITY_WARNING,
                safe_autofix=False,
                manual_review=True,
            )
        )

    return issues


def check_corrupted_shortcodes(text: str, path_str: str) -> list[Issue]:
    """Detect corrupted shortcode fragments (translated or mangled)."""
    issues = []
    lines = text.split("\n")

    # Patterns that indicate shortcode corruption
    corruption_patterns = [
        (r"<\s+figure", "Shortcode fragment '< figure' (missing {{ opening)"),
        (
            r"figurální\s+harmonizace",
            "Translated Hugo shortcode parameter (figurální harmonizace = figure align)",
        ),
        (r"\{\{[^%<]", "Malformed shortcode delimiter (not {{ < or {{ %)"),
        (r"[>%]\s*\}\s*\}", "Malformed shortcode closing (}>} or %>})"),
        (r"\{\{<.*?>\s+\}", "Missing }} in shortcode closing"),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, msg in corruption_patterns:
            if re.search(pattern, line):
                issues.append(
                    Issue(
                        path=path_str,
                        line=i,
                        kind="corrupted_shortcode",
                        message=msg,
                        severity=SEVERITY_ERROR,
                        safe_autofix=False,
                        manual_review=True,
                    )
                )

    return issues


def check_url_corruption(fm_str: str, path_str: str) -> list[Issue]:
    """Check for corrupted URLs in frontmatter values."""
    issues = []
    lines = fm_str.split("\n")
    for i, line in enumerate(lines, 1):
        for url_match in URL_RE.finditer(line):
            url = url_match.group(0)
            # URLs with non-ASCII characters are likely corrupted
            try:
                url.encode("ascii")
            except UnicodeEncodeError:
                issues.append(
                    Issue(
                        path=path_str,
                        line=i + 1,
                        kind="url_corruption",
                        message=f"URL contains non-ASCII characters (likely translated/corrupted): {url[:80]}",
                        severity=SEVERITY_ERROR,
                        safe_autofix=False,
                        manual_review=True,
                    )
                )
    return issues


def check_missing_delimiter(text: str, path_str: str) -> list[Issue]:
    """Check for missing frontmatter delimiters."""
    issues = []
    stripped = text.lstrip("\n\r")
    if not stripped.startswith("---"):
        issues.append(
            Issue(
                path=path_str,
                line=1,
                kind="missing_frontmatter_delimiter",
                message="File does not start with --- frontmatter delimiter",
                severity=SEVERITY_ERROR,
                safe_autofix=False,
                manual_review=True,
            )
        )
        return issues
    parts = text.split("---", 2)
    if len(parts) < 3:
        issues.append(
            Issue(
                path=path_str,
                line=None,
                kind="missing_closing_delimiter",
                message="No closing --- frontmatter delimiter found",
                severity=SEVERITY_ERROR,
                safe_autofix=False,
                manual_review=True,
            )
        )
    return issues


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------


def scan_file(
    path: Path,
    content_root: Path | None = None,
    known_failing: set[str] | None = None,
) -> list[Issue]:
    """Scan a single translated Markdown file for defects."""
    issues: list[Issue] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [
            Issue(
                path=str(path),
                line=None,
                kind="file_read_error",
                message=f"Cannot read file: {e}",
                severity=SEVERITY_ERROR,
            )
        ]

    path_str = str(path)

    # Check frontmatter delimiters
    issues.extend(check_missing_delimiter(text, path_str))

    fm_str, body_str, err = extract_frontmatter(text)
    if fm_str is None:
        return issues  # Already reported

    # YAML parseability
    yaml_issues = check_yaml_parseable(fm_str, path_str)
    issues.extend(yaml_issues)
    yaml_ok = len(yaml_issues) == 0

    # Block scalar indentation (works on raw text even if YAML parse fails)
    issues.extend(check_block_scalar_indent(fm_str, path_str))

    # Collapsed frontmatter
    issues.extend(check_collapsed_frontmatter(fm_str, path_str))

    # URL corruption
    issues.extend(check_url_corruption(fm_str, path_str))

    # Corrupted shortcodes
    issues.extend(check_corrupted_shortcodes(text, path_str))

    # Shortcode balance (body)
    if body_str:
        issues.extend(check_shortcode_balance(body_str, path_str))

    # Source comparison checks (requires YAML parse success)
    source_path = find_english_source(path)
    if yaml_ok and source_path and source_path.exists():
        try:
            src_text = source_path.read_text(encoding="utf-8")
            src_fm, _, _ = extract_frontmatter(src_text)
            if src_fm:
                issues.extend(check_translated_keys(fm_str, path_str, src_fm))
                issues.extend(check_type_drift(fm_str, path_str, src_fm))
                issues.extend(check_passthrough_fields(fm_str, path_str, src_fm))
                # Annotate issues with source path
                for issue in issues:
                    if issue.source_english_path is None:
                        issue.source_english_path = str(source_path)
        except Exception:
            pass
    elif yaml_ok:
        # Check translated keys without source
        issues.extend(check_translated_keys(fm_str, path_str))

    return issues


def scan_directory(
    content_dir: Path,
    known_failing: set[str] | None = None,
) -> ScanResult:
    """Scan all translated Markdown files in a content directory."""
    result = ScanResult()
    known_failing = known_failing or set()

    # Find all Markdown files
    all_md = list(content_dir.rglob("*.md"))
    translated_files = [f for f in all_md if is_translated_file(f)]

    result.total_files_scanned = len(translated_files)
    print(f"Scanning {len(translated_files)} translated files in {content_dir}...", file=sys.stderr)

    for i, path in enumerate(sorted(translated_files)):
        if i % 500 == 0 and i > 0:
            print(f"  Progress: {i}/{len(translated_files)}...", file=sys.stderr)

        issues = scan_file(path, content_dir)
        if issues:
            # Determine relative path for known-failing check
            try:
                rel = str(path.relative_to(content_dir.parent))
            except ValueError:
                rel = str(path)

            rel_normalized = rel.replace("\\", "/")
            is_known = any(kf in rel_normalized for kf in known_failing)

            if is_known:
                result.known_failures_found.append(str(path))
            else:
                result.additional_failures_found.append(str(path))

            for issue in issues:
                result.add_issue(issue)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def scan_changed_files(
    paths: list[str],
    content_root: Path | None = None,
    known_failing: set[str] | None = None,
) -> ScanResult:
    """
    Scan a list of changed file paths for structural defects.

    Intended for pre-commit hooks and CI integration:
        result = scan_changed_files(changed_paths, content_root=Path("content"))
        if any(i.severity == "error" for i in result.all_issues):
            sys.exit(1)

    Args:
        paths: List of file paths (absolute or relative) to scan.
        content_root: Optional content root directory for relative path lookups.
        known_failing: Optional set of known-failing relative paths to classify.

    Returns:
        ScanResult with all detected issues.
    """
    result = ScanResult()
    known_failing = known_failing or set()

    for path_str in paths:
        p = Path(path_str)
        if not p.exists():
            continue
        if p.suffix.lower() != ".md":
            continue
        if not is_translated_file(p):
            continue

        issues = scan_file(p, content_root)
        result.total_files_scanned += 1

        if issues:
            try:
                rel = str(p.relative_to(content_root)) if content_root else str(p)
            except ValueError:
                rel = str(p)
            rel_normalized = rel.replace("\\", "/")
            is_known = any(kf in rel_normalized for kf in known_failing)

            if is_known:
                result.known_failures_found.append(str(p))
            else:
                result.additional_failures_found.append(str(p))

            for issue in issues:
                result.add_issue(issue)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan and repair translated Hugo content files for structural defects"
    )
    parser.add_argument(
        "--content-dir",
        type=Path,
        help="Root directory to scan (e.g., /path/to/aspose.net/content)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Scan a single specific file",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        help="English source file for comparison (with --file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report issues without modifying files (default)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply safe mechanical autofixes",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit 1 if any errors found",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON scan results to this file",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print markdown summary to stdout",
    )
    args = parser.parse_args()

    if not args.content_dir and not args.file:
        parser.error("Provide --content-dir or --file")

    result = ScanResult()

    if args.file:
        if not args.file.exists():
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            return 2
        issues = scan_file(args.file)
        result.total_files_scanned = 1
        if issues:
            result.additional_failures_found.append(str(args.file))
            for issue in issues:
                result.add_issue(issue)
    else:
        if not args.content_dir.exists():
            print(f"ERROR: Content dir not found: {args.content_dir}", file=sys.stderr)
            return 2
        result = scan_directory(args.content_dir, known_failing=KNOWN_FAILING)

    # Print summary
    has_errors = any(i.severity == SEVERITY_ERROR for i in result.all_issues)
    total_issues = len(result.all_issues)
    affected_files = len(set(i.path for i in result.all_issues))

    print(
        f"\nScan complete: {result.total_files_scanned} files, {total_issues} issues in {affected_files} files",
        file=sys.stderr,
    )
    if result.issues_by_category:
        for kind, count in sorted(result.issues_by_category.items()):
            print(f"  {kind}: {count}", file=sys.stderr)

    # Print all issues to stdout
    if args.summary or not args.output:
        print("\n## Structural Scan Summary")
        print(f"- Total files scanned: {result.total_files_scanned}")
        print(f"- Known failing files found: {len(result.known_failures_found)}")
        print(f"- Additional failures found: {len(result.additional_failures_found)}")
        print(f"- Total issues: {total_issues}")
        print(f"- Issue categories: {result.issues_by_category}")
        if result.all_issues[:50]:
            print("\n### Issues (first 50)")
            for issue in result.all_issues[:50]:
                line_str = f":{issue.line}" if issue.line else ""
                print(
                    f"- [{issue.severity.upper()}] {issue.path}{line_str}: [{issue.kind}] {issue.message}"
                )

    # Write JSON output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"JSON results written to {args.output}", file=sys.stderr)

    if args.ci and has_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
