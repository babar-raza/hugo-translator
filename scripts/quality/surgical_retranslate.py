"""
surgical_retranslate.py — Full-disk scan repair for aspose.org translations.

Scans ALL translated files on disk (not JSONL-dependent) and applies surgical repairs
across reference.aspose.org, docs.aspose.org, and kb.aspose.org.

No-GPU repairs (applied immediately with --apply):
  - inline_code_translation   : Restore EN backtick spans (pure string replace)
  - duplicate_content         : Remove repeated paragraphs
  - double_period             : Replace ".." with "." outside code blocks
  - newline_explosion         : Collapse 3+ consecutive blank lines to 2
  - shortcode_leak            : Remove shortcode lines in tgt not present in src
  - artifact_corruption       : Remove body lines with known model artifact patterns
  - eu_hallucination          : Remove GDPR/cookie paragraphs not in source

Model-required (detected only; require GPU retranslation):
  - description_hallucination : Description >3x or <0.3x source length — MUST be retranslated,
                                NOT replaced with English source text
  - table_row_corruption      : Table row count mismatch >50%
  - mixed_language            : English paragraphs in non-Latin target
  - heading_count_mismatch    : Extra or missing headings vs source
  - body_identical_to_en      : Translated body identical to EN source
  - empty_body                : Translation is empty while EN has content
  - purity_issue              : >30% ASCII prose lines in non-Latin locale

Usage:
  python scripts/quality/surgical_retranslate.py --dry-run                  # default
  python scripts/quality/surgical_retranslate.py --apply                    # no-GPU repairs
  python scripts/quality/surgical_retranslate.py --apply --sites all        # all 3 sites
  python scripts/quality/surgical_retranslate.py --dry-run --locales ar,bg,ru
  python scripts/quality/surgical_retranslate.py --apply --issue-type inline_code_translation
  python scripts/quality/surgical_retranslate.py --dry-run --max-files 500
  python scripts/quality/surgical_retranslate.py --apply --update-tm        # also update L2 TM
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure sibling modules (e.g. frontmatter_utils) import correctly regardless
# of invocation mode (direct script run vs. pytest package import).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Content root resolution
# ---------------------------------------------------------------------------

ALL_SITES = ["reference.aspose.org", "docs.aspose.org", "kb.aspose.org"]
EN_LOCALE = "en"

# ---------------------------------------------------------------------------
# Optional TM integration
# ---------------------------------------------------------------------------

try:
    import sys as _sys
    _proj_root = str(Path(__file__).resolve().parent.parent.parent)
    if _proj_root not in _sys.path:
        _sys.path.insert(0, _proj_root)
    from src.tm.l2_persistent import L2PersistentTM  # type: ignore
    _TM_AVAILABLE = True
except ImportError:
    _TM_AVAILABLE = False
    L2PersistentTM = None  # type: ignore

LATIN_SCRIPT_LANGS = frozenset({
    "af", "az", "ca", "cs", "da", "de", "en", "es", "et", "fi",
    "fr", "ga", "hr", "hu", "id", "it", "lt", "lv", "ms", "nl",
    "no", "pl", "pt", "ro", "sk", "sl", "sr", "sv", "tr", "vi",
})

_API_HEADING_TERMS = frozenset({
    "Name", "Type", "Description", "Returns", "Parameters",
    "Properties", "Methods", "Fields", "Constructors", "Events",
    "Exceptions", "Remarks", "Examples", "See Also", "Inheritance",
    "Implements", "Namespace", "Assembly", "Syntax", "Value",
})

_EU_HALLUCINATION_PATTERNS = [
    re.compile(r"(?:cookie|GDPR|General Data Protection|privacy policy|data protection)", re.IGNORECASE),
    re.compile(r"(?:European Union|EU regulation|DSGVO|Datenschutz)", re.IGNORECASE),
]

# Artifact patterns — lines containing these are model output corruption
_ARTIFACT_PATTERNS = [
    re.compile(r"\?\?\?\?+"),                     # repeated question marks (garbled output)
    re.compile(r"\{\\?pos\s*\(\d+,\s*\d+\)\}"),  # SSA subtitle position tags
    re.compile(r"\[Pr[e\xe9]c[e\xe9]dent\]"),     # French "Previous" leaked artifact
    re.compile(r"\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u0439"),  # Cyrillic "Previous"
]

# Shortcode start pattern (Hugo shortcodes: {{< ... >}} and {{% ... %}})
_SHORTCODE_START_RE = re.compile(r"\{\{[<%]")

NON_LATIN_LOCALES = frozenset({
    "ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh",
})


def _resolve_content_root() -> Path:
    env = os.environ.get("ASPOSE_ORG_CONTENT")
    if env:
        p = Path(env)
        if p.exists():
            return p
    defaults = [
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
    ]
    for p in defaults:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate aspose.org content root. Set ASPOSE_ORG_CONTENT env var."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_body(content: str) -> str:
    """Strip frontmatter (--- ... ---) and return the body."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    return content[end + 4:]


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks from text (for line-level analysis)."""
    return re.sub(r"```[\s\S]*?```", "", text)


def _extract_fm_field(content: str, field_name: str) -> str | None:
    """Extract a frontmatter field's raw line (after 'field: '), stripping quotes."""
    m = re.search(
        r"^" + re.escape(field_name) + r":\s*(.+)$",
        content[:2000],
        re.MULTILINE,
    )
    if not m:
        return None
    value = m.group(1).strip()
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        value = value[1:-1]
    return value or None


def _get_fm_section(content: str) -> tuple[str, str]:
    """Split content into (frontmatter_with_delimiters, body). Returns ('', content) if no FM."""
    if not content.startswith("---"):
        return "", content
    end = content.find("\n---", 4)
    if end == -1:
        return "", content
    return content[:end + 4], content[end + 4:]


def _get_table_row_count(text: str) -> int:
    """Count table rows (lines that start AND end with |) in text, excluding code blocks.

    Requires both start and end pipe to match Gate 15 logic and avoid counting
    multi-line cell continuation openers that only start with |.
    """
    clean = _strip_code_blocks(text)
    return sum(
        1
        for line in clean.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    )


# ---------------------------------------------------------------------------
# Corruption detectors
# ---------------------------------------------------------------------------


def _detect_inline_code_translation(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """
    Detect lines where inline code spans were translated.

    Returns list of (line_index, en_line, tr_line, issue_type).
    Only flags lines where an EN ASCII span became non-ASCII in translation.
    """
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_lines = en_body.splitlines()
    tr_lines = tr_body.splitlines()

    issues = []
    in_code = False

    for i, (en_line, tr_line) in enumerate(zip(en_lines, tr_lines)):
        # Track fenced code block boundaries
        if en_line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        en_spans = re.findall(r"`([^`]+)`", en_line)
        tr_spans = re.findall(r"`([^`]+)`", tr_line)
        if not en_spans or not tr_spans:
            continue

        for en_sp, tr_sp in zip(en_spans, tr_spans):
            if en_sp.isascii() and not tr_sp.isascii():
                issues.append((i, en_line, tr_line, "inline_code_translation"))
                break

    return issues


def _repair_inline_code_line(en_line: str, tr_line: str) -> str:
    """
    Replace non-ASCII inline code spans in tr_line with corresponding EN spans.
    Surrounding translated text is preserved exactly.
    """
    en_spans = re.findall(r"`([^`]+)`", en_line)
    tr_spans = re.findall(r"`([^`]+)`", tr_line)

    repaired = tr_line

    if len(en_spans) == len(tr_spans):
        for en_sp, tr_sp in zip(en_spans, tr_spans):
            if en_sp.isascii() and not tr_sp.isascii():
                repaired = repaired.replace(f"`{tr_sp}`", f"`{en_sp}`", 1)
    else:
        # Span count mismatch: replace non-ASCII translated spans by position
        for i, tr_sp in enumerate(tr_spans):
            if not tr_sp.isascii() and i < len(en_spans):
                repaired = repaired.replace(f"`{tr_sp}`", f"`{en_spans[i]}`", 1)

    return repaired


def _detect_duplicate_content(tr_content: str) -> list[tuple[int, str, str, str]]:
    """Detect paragraphs appearing 3+ times in body.

    Code-fence content is excluded: distinct code examples on the same page
    routinely share a short boilerplate opening line (an import/#include
    right after the fence, separated from the rest of the snippet by a blank
    line), which would otherwise be miscounted as "the same paragraph
    repeated" even though every example is genuinely different.
    """
    body = _get_body(tr_content)
    non_fence_chunks = [
        part for part in re.split(r"(```[\s\S]*?```)", body)
        if not part.startswith("```")
    ]
    paragraphs = [
        p.strip()
        for chunk in non_fence_chunks
        for p in re.split(r"\n{2,}", chunk)
        if len(p.strip()) > 30
    ]

    counts: dict[str, int] = {}
    for p in paragraphs:
        counts[p] = counts.get(p, 0) + 1

    duplicates = [p for p, c in counts.items() if c >= 3]
    if duplicates:
        return [(0, "", tr_content, "duplicate_content")]
    return []


def _fix_duplicate_content(tr_content: str) -> str:
    """Remove duplicate paragraphs (keep first occurrence); code-fence content is left untouched."""
    # Split into frontmatter and body
    if tr_content.startswith("---"):
        end = tr_content.find("\n---", 4)
        if end != -1:
            fm = tr_content[:end + 4]
            body = tr_content[end + 4:]
        else:
            fm = ""
            body = tr_content
    else:
        fm = ""
        body = tr_content

    seen: set[str] = set()

    def _dedupe_chunk(chunk: str) -> str:
        segments = re.split(r"(\n{2,})", chunk)
        result = []
        for segment in segments:
            stripped = segment.strip()
            if len(stripped) > 30:
                if stripped in seen:
                    continue  # skip duplicate
                seen.add(stripped)
            result.append(segment)
        return "".join(result)

    fence_parts = re.split(r"(```[\s\S]*?```)", body)
    fixed_parts = [
        part if part.startswith("```") else _dedupe_chunk(part)
        for part in fence_parts
    ]

    return fm + "".join(fixed_parts)


def _detect_double_periods(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect '..' (not '...') in body outside code blocks."""
    body = _get_body(tr_content)
    clean = _strip_code_blocks(body)
    if re.search(r"(?<!\.)\.\.(?!\.)", clean):
        return [(0, "", tr_content, "double_period")]
    return []


def _fix_double_periods(tr_content: str) -> str:
    """Replace '..' with '.' (but not '...') outside code blocks."""
    if tr_content.startswith("---"):
        end = tr_content.find("\n---", 4)
        if end != -1:
            fm = tr_content[:end + 4]
            body = tr_content[end + 4:]
        else:
            fm = ""
            body = tr_content
    else:
        fm = ""
        body = tr_content

    # Only replace in non-code-block sections
    def _fix_segment(seg: str) -> str:
        return re.sub(r"(?<!\.)\.\.(?!\.)", ".", seg)

    parts = re.split(r"(```[\s\S]*?```)", body)
    fixed_parts = [
        part if re.match(r"```", part.strip()) else _fix_segment(part)
        for part in parts
    ]
    return fm + "".join(fixed_parts)


def _detect_description_hallucination(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect description field with >3x or <0.3x the source length.

    Parses frontmatter via HugoParser rather than a first-line regex, so
    multi-line folded/literal scalars are compared by their full value
    instead of being truncated to the first physical line (TC-HT-001).
    """
    from frontmatter_utils import get_frontmatter_field

    en_desc = get_frontmatter_field(en_content, "description")
    tr_desc = get_frontmatter_field(tr_content, "description")
    if not en_desc or not tr_desc:
        return []

    ratio = len(tr_desc) / max(len(en_desc), 1)
    if ratio > 3.0 or ratio < 0.3:
        return [(0, en_desc, tr_desc, "description_hallucination")]
    return []


def _detect_table_corruption(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect table row count mismatch >50%.

    EN source is normalized before counting (multi-line cell openers merged into
    single-line rows) so that repaired translations with single-line cells are not
    false-positively flagged as corrupted.
    """
    from src.translation_engine.parser.hugo_parser import normalize_table_cells

    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_rows = _get_table_row_count(normalize_table_cells(en_body))
    tr_rows = _get_table_row_count(tr_body)

    if en_rows < 4:
        return []  # Too small to reliably detect

    if tr_rows < en_rows * 0.5 or tr_rows > en_rows * 2.0:
        return [(0, str(en_rows), str(tr_rows), "table_row_corruption")]
    return []


_PASCAL_RE = re.compile(r"^[A-Z][a-z0-9]{3,}(?:[A-Z][a-z0-9]*)*$")
_DOTTED_RE = re.compile(r"^[A-Z][A-Za-z0-9]*\.[A-Z]")
_IFACE_RE = re.compile(r"^I[A-Z][a-zA-Z]{2,}$")
_ALLCAPS_RE = re.compile(r"^[A-Z_]{2,}$")


def _cell_is_non_translatable(cell: str) -> bool:
    """Return True if a table cell should stay in English (API term or identifier)."""
    c = cell.strip()
    if not c:
        return True
    if c in _API_HEADING_TERMS:
        return True
    if _PASCAL_RE.match(c):
        return True
    if _DOTTED_RE.match(c):
        return True
    if _IFACE_RE.match(c):
        return True
    if _ALLCAPS_RE.match(c):
        return True
    return False


def _build_table_from_ast(table_node, NodeType) -> str:
    """Render a TABLE AST node back to a markdown table string."""

    def _walk(node):
        yield node
        for child in getattr(node, "children", []):
            yield from _walk(child)

    def _cell_text(cell_node) -> str:
        parts = []
        for n in _walk(cell_node):
            if not hasattr(n, "raw") or not n.raw:
                continue
            if n.type == NodeType.CODE_SPAN:
                parts.append(f"`{n.raw.strip()}`")
            elif n.type == NodeType.TEXT:
                parts.append(n.raw)
        return " ".join(parts).strip()

    rows_data: list[tuple[bool, list[str], list[str]]] = []
    for row_node in table_node.children:
        if row_node.type != NodeType.TABLE_ROW:
            continue
        is_header = bool(row_node.attrs.get("is_header", False))
        cells, aligns = [], []
        for cell_node in row_node.children:
            if cell_node.type != NodeType.TABLE_CELL:
                continue
            cells.append(_cell_text(cell_node))
            aligns.append(cell_node.attrs.get("align") or "left")
        rows_data.append((is_header, cells, aligns))

    if not rows_data:
        return ""

    col_count = max(len(r[1]) for r in rows_data)
    header_aligns = rows_data[0][2] if rows_data else ["left"] * col_count
    widths: list[int] = [3] * col_count
    for c in range(col_count):
        for _, cells, _ in rows_data:
            if c < len(cells):
                widths[c] = max(widths[c], len(cells[c]))

    lines: list[str] = []
    for row_idx, (_, cells, _) in enumerate(rows_data):
        row_cells = [
            (cells[c] if c < len(cells) else "").ljust(widths[c])
            for c in range(col_count)
        ]
        lines.append("| " + " | ".join(row_cells) + " |")
        if row_idx == 0:
            sep = []
            for c in range(col_count):
                align = header_aligns[c] if c < len(header_aligns) else "left"
                w = widths[c]
                if align == "center":
                    sep.append(":" + "-" * max(w - 2, 1) + ":")
                elif align == "right":
                    sep.append("-" * max(w - 1, 2) + ":")
                else:
                    sep.append("-" * w)
            lines.append("| " + " | ".join(sep) + " |")

    return "\n".join(lines) + "\n"


def _repair_too_few_blocks(
    en_content: str,
    tr_content: str,
    tables: list,
    tr_matches: list,
    table_re,
) -> tuple[str, int]:
    """Fallback repair for when TR has fewer table blocks than EN has tables.

    Rebuilds all EN tables from AST and substitutes them into TR content:
    - Existing TR table blocks are replaced 1:1 with corresponding EN tables.
    - If TR has fewer blocks than EN tables, remaining EN tables are appended
      directly after the last replaced block (separated by a blank line).

    All cell content comes from the EN source AST — identifiers and API terms
    stay in English (correct), description text stays in English (placeholder;
    shards will retranslate on next run with the fixed pipeline).
    """
    try:
        _proj_root = str(Path(__file__).resolve().parent.parent.parent)
        if _proj_root not in sys.path:
            sys.path.insert(0, _proj_root)
        from src.translation_engine.parser.ast_nodes import NodeType  # type: ignore
    except ImportError:
        return tr_content, 0

    en_table_texts = [_build_table_from_ast(t, NodeType) for t in tables]
    en_table_texts = [t for t in en_table_texts if t]
    if not en_table_texts:
        return tr_content, 0

    repaired = tr_content
    offset = 0
    fixed = 0
    last_insert_pos = len(tr_content)  # fallback: end of file

    for i, en_table_text in enumerate(en_table_texts):
        if i < len(tr_matches):
            # Replace existing TR block with EN table
            m = tr_matches[i]
            start = m.start() + offset
            end = m.end() + offset
            repaired = repaired[:start] + en_table_text + repaired[end:]
            offset += len(en_table_text) - (m.end() - m.start())
            last_insert_pos = start + len(en_table_text)
            fixed += 1
        else:
            # Append remaining EN tables after the last inserted/replaced position
            insertion = "\n" + en_table_text
            repaired = repaired[:last_insert_pos] + insertion + repaired[last_insert_pos:]
            last_insert_pos += len(insertion)
            offset += len(insertion)
            fixed += 1

    return repaired, fixed


def _repair_table_corruption_no_gpu(
    en_content: str,
    tr_content: str,
) -> tuple[str, int]:
    """
    Repair table row corruption using English source structure as template (no GPU).

    TC-TBL-012 / surgical repair:
    Uses HugoParser to extract the SOURCE table's row/column structure (the authoritative
    template) and renders a new table with that structure. Cell content:
      - Non-translatable cells (API heading terms, PascalCase/dotted identifiers):
        English is the correct value — passthrough unchanged.
      - Translatable description/summary cells: kept in English as a structural
        placeholder. The shards will provide proper translations on next run (now
        that Layers 1+2 prevent the legacy fallback that caused the corruption).

    Row count is structurally guaranteed correct (taken from source, never from model).

    Returns (repaired_content, num_tables_fixed).
    """
    try:
        _proj_root = str(Path(__file__).resolve().parent.parent.parent)
        if _proj_root not in sys.path:
            sys.path.insert(0, _proj_root)
        from src.translation_engine.parser.hugo_parser import HugoParser  # type: ignore
        from src.translation_engine.parser.ast_nodes import NodeType  # type: ignore
    except ImportError:
        return tr_content, 0

    try:
        parser = HugoParser()
        en_doc = parser.parse_string(en_content)
    except Exception:
        return tr_content, 0

    def _walk(node):
        yield node
        for child in getattr(node, "children", []):
            yield from _walk(child)

    def _cell_text(cell_node) -> str:
        parts = []
        for n in _walk(cell_node):
            if not hasattr(n, "raw") or not n.raw:
                continue
            if n.type == NodeType.CODE_SPAN:
                parts.append(f"`{n.raw.strip()}`")
            elif n.type == NodeType.TEXT:
                parts.append(n.raw)
        return " ".join(parts).strip()

    # en_doc.ast may be a list of root nodes or a single root node
    ast_roots = en_doc.ast if isinstance(en_doc.ast, list) else ([en_doc.ast] if en_doc.ast else [])
    tables = [n for root in ast_roots for n in _walk(root) if n.type == NodeType.TABLE]
    if not tables:
        return tr_content, 0

    # Locate table blocks in TR content (contiguous lines starting with |)
    _TABLE_BLOCK_RE = re.compile(r"((?:^[ \t]*\|[^\n]*\n)+)", re.MULTILINE)
    tr_table_matches = list(_TABLE_BLOCK_RE.finditer(tr_content))
    if len(tr_table_matches) < len(tables):
        # Fallback for "too few blocks" (model dropped entire tables):
        # Rebuild all EN tables from AST and replace/append into TR content.
        return _repair_too_few_blocks(en_content, tr_content, tables, tr_table_matches, _TABLE_BLOCK_RE)

    repaired = tr_content
    offset = 0
    tables_fixed = 0

    for en_table, tr_match in zip(tables, tr_table_matches):
        # Extract rows: (is_header, [cell_text, ...], [align, ...])
        rows_data: list[tuple[bool, list[str], list[str]]] = []
        for row_node in en_table.children:
            if row_node.type != NodeType.TABLE_ROW:
                continue
            is_header = bool(row_node.attrs.get("is_header", False))
            cells = []
            aligns = []
            for cell_node in row_node.children:
                if cell_node.type != NodeType.TABLE_CELL:
                    continue
                cells.append(_cell_text(cell_node))
                aligns.append(cell_node.attrs.get("align") or "left")
            rows_data.append((is_header, cells, aligns))

        if not rows_data:
            continue

        col_count = max(len(r[1]) for r in rows_data)
        header_aligns = rows_data[0][2] if rows_data else ["left"] * col_count

        # Column widths
        widths: list[int] = []
        for c in range(col_count):
            w = 3  # minimum for separator ---
            for _, cells, _ in rows_data:
                if c < len(cells):
                    w = max(w, len(cells[c]))
            widths.append(w)

        def _pad(text: str, width: int) -> str:
            return text.ljust(width)

        lines: list[str] = []
        for row_idx, (is_header, cells, _) in enumerate(rows_data):
            row_cells = [
                _pad(cells[c] if c < len(cells) else "", widths[c])
                for c in range(col_count)
            ]
            lines.append("| " + " | ".join(row_cells) + " |")
            if row_idx == 0:
                # Separator row after header
                sep_parts = []
                for c in range(col_count):
                    align = header_aligns[c] if c < len(header_aligns) else "left"
                    w = widths[c]
                    if align == "center":
                        sep_parts.append(":" + "-" * max(w - 2, 1) + ":")
                    elif align == "right":
                        sep_parts.append("-" * max(w - 1, 2) + ":")
                    else:
                        sep_parts.append("-" * w)
                lines.append("| " + " | ".join(sep_parts) + " |")

        repaired_table = "\n".join(lines) + "\n"

        # Replace corrupted block in repaired string (offset-adjusted for prior repairs)
        tr_start = tr_match.start() + offset
        tr_end = tr_match.end() + offset
        repaired = repaired[:tr_start] + repaired_table + repaired[tr_end:]
        offset += len(repaired_table) - (tr_end - tr_start)
        tables_fixed += 1

    # Remove any extra TR table blocks beyond what EN has (hallucinated extra tables).
    # Re-scan the repaired content for remaining unmatched blocks and delete them.
    if len(tr_table_matches) > len(tables):
        extra_count = len(tr_table_matches) - len(tables)
        # Re-find all table blocks in the current repaired content
        extra_blocks = list(_TABLE_BLOCK_RE.finditer(repaired))
        # Keep only the first len(tables) blocks; remove the rest
        to_remove = extra_blocks[len(tables):]
        rm_offset = 0
        for blk in to_remove:
            start = blk.start() + rm_offset
            end = blk.end() + rm_offset
            repaired = repaired[:start] + repaired[end:]
            rm_offset -= (end - start)
            tables_fixed += 1

    return repaired, tables_fixed


def _detect_mixed_language(
    tr_content: str, target_lang: str
) -> list[tuple[int, str, str, str]]:
    """Detect fully-English paragraphs in non-Latin target translations."""
    if target_lang in LATIN_SCRIPT_LANGS:
        return []  # Latin-script target — can't distinguish

    body = _get_body(tr_content)
    clean = _strip_code_blocks(body)

    issues = []
    for line in clean.splitlines():
        stripped = line.strip()
        if len(stripped) < 20 or "|" in stripped or stripped.startswith(">"):
            continue
        words = stripped.split()
        if len(words) < 5:
            continue
        if re.fullmatch(r"[A-Za-z0-9\s.,;:!?\-\'\"()\[\]{}#@_/\\`*]+", stripped):
            issues.append((0, "", stripped, "mixed_language"))

    if len(issues) > 3:
        return [(0, "", tr_content, "mixed_language")]
    return []


def _detect_heading_mismatch(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect heading count mismatch vs source."""
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_headings = re.findall(r"^#{1,6}\s+.+$", en_body, re.MULTILINE)
    tr_headings = re.findall(r"^#{1,6}\s+.+$", tr_body, re.MULTILINE)

    if len(en_headings) == 0:
        return []

    if len(tr_headings) != len(en_headings):
        return [(0, str(len(en_headings)), str(len(tr_headings)), "heading_count_mismatch")]
    return []


def _detect_eu_hallucination(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect EU/GDPR text in translation not present in source."""
    tr_body = _get_body(tr_content)
    en_body = _get_body(en_content)

    for pattern in _EU_HALLUCINATION_PATTERNS:
        if pattern.search(tr_body) and not pattern.search(en_body):
            return [(0, "", "", "eu_hallucination")]
    return []


def _detect_newline_explosion(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect >2.5x newlines vs source body."""
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_lines = en_body.count("\n")
    tr_lines = tr_body.count("\n")

    if en_lines < 5:
        return []
    if tr_lines > en_lines * 2.5:
        return [(0, str(en_lines), str(tr_lines), "newline_explosion")]
    return []


def _detect_shortcode_leak(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect shortcode patterns in tgt body not present in src body."""
    src_body = _get_body(en_content)
    tgt_body = _get_body(tr_content)
    src_codes = set(_SHORTCODE_START_RE.findall(src_body))
    tgt_codes = set(_SHORTCODE_START_RE.findall(tgt_body))
    if tgt_codes - src_codes:
        return [(0, "", "", "shortcode_leak")]
    return []


def _detect_artifact_corruption(
    tr_content: str,
) -> list[tuple[int, str, str, str]]:
    """Detect known model artifact patterns in body."""
    body = _get_body(tr_content)
    for pat in _ARTIFACT_PATTERNS:
        if pat.search(body):
            return [(0, "", "", "artifact_corruption")]
    return []


def detect_all_corruption(
    en_content: str, tr_content: str, target_lang: str
) -> list[tuple[int, str, str, str]]:
    """Run all detectors. Returns list of (line_idx, en_text, tr_text, issue_type)."""
    issues = []
    issues += _detect_inline_code_translation(en_content, tr_content)
    issues += _detect_duplicate_content(tr_content)
    issues += _detect_double_periods(en_content, tr_content)
    issues += _detect_description_hallucination(en_content, tr_content)
    issues += _detect_table_corruption(en_content, tr_content)
    issues += _detect_mixed_language(tr_content, target_lang)
    issues += _detect_heading_mismatch(en_content, tr_content)
    issues += _detect_eu_hallucination(en_content, tr_content)
    issues += _detect_newline_explosion(en_content, tr_content)
    issues += _detect_shortcode_leak(en_content, tr_content)
    issues += _detect_artifact_corruption(tr_content)
    return issues


# ---------------------------------------------------------------------------
# New no-GPU repair functions
# ---------------------------------------------------------------------------
# NOTE: description_hallucination is intentionally NOT repaired here — a
# regex line-substitution "fix" (formerly _fix_description_hallucination)
# truncated multi-line YAML scalars and left unterminated quotes, which was
# the root cause of the 2026-07-12 wave-3 corruption (TC-HT-001). Files with
# this issue must be GPU-retranslated, never patched with English source text.


def _fix_newline_explosion(tr_content: str) -> str:
    """Collapse runs of 3+ consecutive newlines down to 2 (one blank line max)."""
    return re.sub(r"\n{3,}", "\n\n", tr_content)


def _fix_shortcode_leak(en_content: str, tr_content: str) -> str:
    """Remove shortcode lines from tgt body that are not present in src body.

    Fence-aware (TC-HT-002): only scans/drops lines in UNFENCED segments, so
    a shortcode-like string shown as example code inside a fenced block is
    never touched.
    """
    from fence_spans import split_fenced_segments

    src_body = _get_body(en_content)
    # Build set of shortcode-containing stripped lines from src
    src_shortcode_lines: set[str] = set()
    for line in src_body.splitlines():
        if _SHORTCODE_START_RE.search(line):
            src_shortcode_lines.add(line.strip())

    fm, body = _get_fm_section(tr_content)
    result_lines = []
    for is_fenced, lines in split_fenced_segments(body):
        if is_fenced:
            result_lines.extend(lines)
            continue
        for line in lines:
            if _SHORTCODE_START_RE.search(line) and line.strip() not in src_shortcode_lines:
                continue  # drop leaked shortcode line
            result_lines.append(line)
    return fm + "".join(result_lines)


def _fix_artifact_corruption(tr_content: str) -> str:
    """Remove body lines containing known model artifact patterns.

    Fence-aware (TC-HT-002): only drops lines in UNFENCED segments.
    """
    from fence_spans import split_fenced_segments

    fm, body = _get_fm_section(tr_content)
    result_lines = []
    for is_fenced, lines in split_fenced_segments(body):
        if is_fenced:
            result_lines.extend(lines)
            continue
        result_lines.extend(
            line for line in lines
            if not any(p.search(line) for p in _ARTIFACT_PATTERNS)
        )
    return fm + "".join(result_lines)


def _fix_eu_hallucination(en_content: str, tr_content: str) -> str:
    """Remove EU/GDPR paragraphs from tgt body that are not present in src.

    Fence-aware (TC-HT-002): a paragraph chunk that overlaps any fenced line
    is never scanned/dropped — a code example that happens to mention
    "cookie" is preserved. Paragraph-splitting runs over the WHOLE body
    first (not per-fence-segment) so a blank-line separator immediately
    after a closing fence is still recognized as a paragraph break.
    """
    from fence_spans import fenced_line_mask

    src_body = _get_body(en_content)
    # Check which EU patterns fire in src (those are legitimate)
    src_eu = {i for i, p in enumerate(_EU_HALLUCINATION_PATTERNS) if p.search(src_body)}

    fm, body = _get_fm_section(tr_content)
    mask = fenced_line_mask(body)

    result = []
    pos = 0
    for chunk in re.split(r"(\n{2,})", body):
        start_line = body[:pos].count("\n")
        end_line = start_line + chunk.count("\n") + (0 if chunk.endswith("\n") else 1)
        if any(mask[start_line:end_line]):
            result.append(chunk)  # overlaps a fenced line: never touch
            pos += len(chunk)
            continue

        is_hallucinated = any(
            i not in src_eu and p.search(chunk)
            for i, p in enumerate(_EU_HALLUCINATION_PATTERNS)
        )
        if not is_hallucinated:
            result.append(chunk)
        pos += len(chunk)
    return fm + "".join(result)


# ---------------------------------------------------------------------------
# Per-file repair (no-GPU only)
# ---------------------------------------------------------------------------


def _apply_no_gpu_repairs(en_content: str, tr_content: str) -> tuple[str, list[str]]:
    """
    Apply all no-GPU repairs to tr_content.
    Returns (repaired_content, list_of_applied_fixes).
    """
    working = tr_content
    applied = []

    # 1. Inline code translation repair
    inline_issues = _detect_inline_code_translation(en_content, working)
    if inline_issues:
        en_body = _get_body(en_content)
        tr_body = _get_body(working)
        en_lines = en_body.splitlines()
        tr_lines = tr_body.splitlines()

        if len(en_lines) != len(tr_lines):
            # TC-HT-002: hard-bail instead of zip()'s silent shortest-wins
            # truncation, which used to drop trailing lines whenever EN/TR
            # line counts diverged.
            applied.append("inline_code_translation_skipped_line_count_mismatch")
        else:
            repaired_lines = list(tr_lines)

            in_code = False
            for i, (en_line, tr_line) in enumerate(zip(en_lines, tr_lines)):
                if en_line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                repaired_line = _repair_inline_code_line(en_line, tr_line)
                if repaired_line != tr_line:
                    repaired_lines[i] = repaired_line

            # Reconstruct with repaired body
            if working.startswith("---"):
                end = working.find("\n---", 4)
                if end != -1:
                    fm = working[:end + 4]
                    new_body = "\n".join(repaired_lines)
                    working = fm + "\n" + new_body if not new_body.startswith("\n") else fm + new_body
                # edge case: no proper body separator — skip
            applied.append(f"inline_code_translation:{len(inline_issues)}_lines")

    # 2. Duplicate content
    if _detect_duplicate_content(working):
        working = _fix_duplicate_content(working)
        applied.append("duplicate_content")

    # 3. Double periods
    if _detect_double_periods(en_content, working):
        working = _fix_double_periods(working)
        applied.append("double_period")

    # 4. Table row corruption — rebuild from EN source structure (no GPU needed)
    if _detect_table_corruption(en_content, working):
        repaired_table, n_fixed = _repair_table_corruption_no_gpu(en_content, working)
        if n_fixed > 0:
            working = repaired_table
            applied.append(f"table_row_corruption:{n_fixed}_tables")

    # NOTE: description_hallucination is intentionally NOT repaired here.
    # Descriptions must be retranslated by GPU, not replaced with English source text.

    # 5. Newline explosion — collapse 3+ blank lines to 1
    if _detect_newline_explosion(en_content, working):
        fixed = _fix_newline_explosion(working)
        if fixed != working:
            working = fixed
            applied.append("newline_explosion")

    # 7. Shortcode leak — remove shortcode lines not in source
    if _detect_shortcode_leak(en_content, working):
        fixed = _fix_shortcode_leak(en_content, working)
        if fixed != working:
            working = fixed
            applied.append("shortcode_leak")

    # 8. Artifact corruption — remove lines with known bad model output patterns
    if _detect_artifact_corruption(working):
        fixed = _fix_artifact_corruption(working)
        if fixed != working:
            working = fixed
            applied.append("artifact_corruption")

    # 9. EU hallucination — remove GDPR/cookie paragraphs not in source
    if _detect_eu_hallucination(en_content, working):
        fixed = _fix_eu_hallucination(en_content, working)
        if fixed != working:
            working = fixed
            applied.append("eu_hallucination")

    return working, applied


# ---------------------------------------------------------------------------
# File walker
# ---------------------------------------------------------------------------


def process_file(
    tr_path: Path,
    en_path: Path,
    locale: str,
    apply: bool,
    only_issues: set[str] | None,
    stats: dict,
    verbose: bool,
    site_id: str = "reference.aspose.org",
    tm: object | None = None,
) -> None:
    if not en_path.exists():
        stats["en_missing"] += 1
        return

    try:
        tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
        en_content = en_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stats["read_errors"] += 1
        return

    issues = detect_all_corruption(en_content, tr_content, locale)

    if only_issues:
        issues = [iss for iss in issues if iss[3] in only_issues]

    if not issues:
        stats["files_clean"] += 1
        return

    stats["files_with_issues"] += 1
    issue_types = {iss[3] for iss in issues}
    for it in issue_types:
        stats[f"issue_{it}"] += 1

    if verbose:
        rel = str(tr_path).replace(str(tr_path.parent.parent.parent.parent), "...")
        print(f"  [{', '.join(sorted(issue_types))}] {rel}")

    # Determine which issues are no-GPU fixable
    # NOTE: description_hallucination is NOT in this set — descriptions must be
    # retranslated by the GPU engine, not replaced with English source text.
    no_gpu_issue_types = {
        "inline_code_translation", "duplicate_content", "double_period",
        "table_row_corruption", "newline_explosion",
        "shortcode_leak", "artifact_corruption", "eu_hallucination",
    }
    has_no_gpu = bool(issue_types & no_gpu_issue_types)
    has_model_needed = bool(issue_types - no_gpu_issue_types)

    if has_model_needed:
        for it in issue_types - no_gpu_issue_types:
            stats[f"model_needed_{it}"] += 1

    if apply and has_no_gpu:
        repaired, applied = _apply_no_gpu_repairs(en_content, tr_content)
        if repaired != tr_content:
            import safe_io

            frontmatter, body = safe_io.parse_content(repaired)
            save_result = safe_io.save(
                tr_path, tr_path, frontmatter, body,
                source_content=en_content, target_lang=locale,
            )
            if not save_result.written:
                stats["write_gate_blocked"] += 1
                print(
                    f"  QUARANTINED (write gate blocked): {tr_path} — {save_result.reasons}",
                    file=sys.stderr,
                )
                return
            try:
                stats["files_repaired"] += 1
                for a in applied:
                    stats[f"repaired_{a.split(':')[0]}"] += 1

                # Update L2 TM: store repaired inline-code lines so future
                # retranslations pick up the corrected form from TM hit.
                if tm is not None and "inline_code_translation" in {a.split(":")[0] for a in applied}:
                    _update_tm_inline_code(
                        tm, site_id, locale, en_content, repaired, stats
                    )

            except OSError as e:
                print(f"  ERROR updating TM for {tr_path}: {e}", file=sys.stderr)
                stats["write_errors"] += 1


def _update_tm_inline_code(
    tm: object,
    site_id: str,
    locale: str,
    en_content: str,
    repaired_content: str,
    stats: dict,
) -> None:
    """Store repaired body lines into L2 TM as (en_line -> repaired_line) pairs.

    Only stores lines where the repaired content differs from the English source
    (i.e., the translated surrounding text is preserved, only the backtick spans
    were corrected). Pure passthrough lines (en == repaired) are skipped to avoid
    polluting the TM with identity entries that bypass future translation.
    """
    try:
        en_body = _get_body(en_content)
        rep_body = _get_body(repaired_content)
        en_lines = en_body.splitlines()
        rep_lines = rep_body.splitlines()

        stored = 0
        for en_line, rep_line in zip(en_lines, rep_lines):
            en_stripped = en_line.strip()
            rep_stripped = rep_line.strip()
            if not en_stripped or rep_stripped == en_stripped:
                continue  # skip empty or identity
            # Only store if EN line has backtick spans (this is an inline-code line)
            if not re.search(r"`[^`]+`", en_stripped):
                continue
            try:
                tm.store(  # type: ignore[attr-defined]
                    site_id=site_id,
                    src_lang="en",
                    tgt_lang=locale,
                    text=en_stripped,
                    translation=rep_stripped,
                    overwrite=True,
                )
                stored += 1
            except Exception:
                pass  # TM store failure is non-fatal

        if stored:
            stats["tm_entries_stored"] = stats.get("tm_entries_stored", 0) + stored
    except Exception:
        pass  # TM update failure is always non-fatal


def run(
    content_root: Path,
    only_locales: list[str] | None,
    apply: bool,
    only_issues: set[str] | None,
    max_files: int | None,
    verbose: bool,
    sites: list[str] | None = None,
    update_tm: bool = False,
    tm_db_path: Path | None = None,
) -> dict:
    sites_to_run = sites if sites else ["reference.aspose.org"]
    stats: dict = defaultdict(int)

    # Open TM once for all sites if requested
    tm = None
    if apply and update_tm and _TM_AVAILABLE:
        _db = tm_db_path or (
            Path(__file__).resolve().parent.parent.parent / "data" / "tm" / "l2.lmdb"
        )
        try:
            tm = L2PersistentTM(db_path=_db)
            print(f"TM: {_db} (update-tm enabled)")
        except Exception as e:
            print(f"WARNING: TM open failed ({e}); continuing without TM update", file=sys.stderr)
    elif apply and update_tm and not _TM_AVAILABLE:
        print("WARNING: L2PersistentTM not importable; --update-tm skipped", file=sys.stderr)

    print(f"Mode: {'APPLY (no-GPU repairs)' if apply else 'DRY-RUN'}")
    if only_issues:
        print(f"Issue filter: {', '.join(sorted(only_issues))}")
    print()

    files_processed = 0

    for site_id in sites_to_run:
        site_root = content_root / site_id
        if not site_root.exists():
            print(f"  SKIP {site_id}: not found at {site_root}")
            continue

        en_root = site_root / EN_LOCALE

        locales = sorted(
            d.name
            for d in site_root.iterdir()
            if d.is_dir() and d.name != EN_LOCALE
            and (not only_locales or d.name in only_locales)
        )

        print(f"Site: {site_id}  ({len(locales)} locales)")

        for locale in locales:
            locale_root = site_root / locale
            locale_files = list(locale_root.rglob("*.md"))

            print(f"  {locale}: {len(locale_files)} files", end="", flush=True)

            for tr_path in locale_files:
                if max_files and files_processed >= max_files:
                    break
                stats["files_scanned"] += 1
                files_processed += 1

                rel = tr_path.relative_to(locale_root)
                en_path = en_root / rel
                process_file(
                    tr_path, en_path, locale, apply, only_issues, stats, verbose,
                    site_id=site_id, tm=tm,
                )

            print(f"  (scanned={stats['files_scanned']}, with_issues={stats['files_with_issues']})")

            if max_files and files_processed >= max_files:
                print(f"  Reached --max-files={max_files} limit.")
                break

        if max_files and files_processed >= max_files:
            break

        print()

    return dict(stats)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surgical per-file repair for aspose.org translations (all sites)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Report issues only (default)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply no-GPU repairs in place",
    )
    parser.add_argument(
        "--content-root", type=Path,
        help="Path to aspose.org/content directory",
    )
    parser.add_argument(
        "--sites", type=str, default="reference.aspose.org",
        help="Comma-separated site names or 'all' (default: reference.aspose.org)",
    )
    parser.add_argument(
        "--locales", type=str,
        help="Comma-separated locales to restrict (default: all)",
    )
    parser.add_argument(
        "--issue-type", type=str,
        help="Comma-separated issue types to filter (default: all)",
    )
    parser.add_argument(
        "--max-files", type=int,
        help="Maximum files to process (for testing)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print each file with issues",
    )
    parser.add_argument(
        "--update-tm", action="store_true",
        help="Update L2 TM with repaired inline-code translations (requires --apply)",
    )
    parser.add_argument(
        "--tm-db", type=Path,
        help="Path to L2 LMDB file (default: data/tm/l2.lmdb)",
    )
    args = parser.parse_args()

    apply = args.apply
    content_root = args.content_root or _resolve_content_root()
    only_locales = [loc.strip() for loc in args.locales.split(",")] if args.locales else None
    only_issues = (
        {i.strip() for i in args.issue_type.split(",")}
        if args.issue_type else None
    )
    if args.sites.lower() == "all":
        sites = ALL_SITES
    else:
        sites = [s.strip() for s in args.sites.split(",")]

    stats = run(
        content_root=content_root,
        only_locales=only_locales,
        apply=apply,
        only_issues=only_issues,
        max_files=args.max_files,
        verbose=args.verbose,
        sites=sites,
        update_tm=args.update_tm,
        tm_db_path=args.tm_db,
    )

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files scanned:              {stats.get('files_scanned', 0):>8,}")
    print(f"Files clean:                {stats.get('files_clean', 0):>8,}")
    print(f"Files with issues:          {stats.get('files_with_issues', 0):>8,}")
    print()

    issue_keys = [k for k in sorted(stats) if k.startswith("issue_")]
    if issue_keys:
        print("Issue counts (files affected):")
        for k in issue_keys:
            label = k.replace("issue_", "")
            print(f"  {label:35s} {stats[k]:>6,}")
        print()

    model_keys = [k for k in sorted(stats) if k.startswith("model_needed_")]
    if model_keys:
        print("Requires model retranslation (not repaired by this script):")
        for k in model_keys:
            label = k.replace("model_needed_", "")
            print(f"  {label:35s} {stats[k]:>6,}")
        print()

    if apply:
        print(f"Files repaired (no-GPU):    {stats.get('files_repaired', 0):>8,}")
        repair_keys = [k for k in sorted(stats) if k.startswith("repaired_")]
        for k in repair_keys:
            print(f"  {k.replace('repaired_', ''):35s} {stats[k]:>6,}")
        if stats.get("tm_entries_stored"):
            print(f"TM entries stored:          {stats.get('tm_entries_stored', 0):>8,}")
        print(f"Write errors:               {stats.get('write_errors', 0):>8,}")

    print(f"EN source missing:          {stats.get('en_missing', 0):>8,}")
    print(f"Read errors:                {stats.get('read_errors', 0):>8,}")
    print()

    if not apply:
        print("DRY-RUN complete. Run with --apply to apply no-GPU repairs.")
        if model_keys:
            model_needed_count = sum(stats.get(k, 0) for k in model_keys)
            print(f"  {model_needed_count} files need model retranslation (future work).")
    else:
        print("APPLY complete (no-GPU repairs applied).")


if __name__ == "__main__":
    main()
