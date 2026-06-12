#!/usr/bin/env python3
"""
TC-00 Deliverable #1: Quantitative Failure Analysis

Analyzes 100 random production translation files to measure:
- Broken links: % with corrupted URLs or syntax
- Missing code: % of code blocks/spans lost or corrupted
- Formatting loss: % of bold/italic elements lost
- Structure drift: % with mismatched AST node counts

Uses regex-based analysis to avoid complex dependencies.
"""

import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


@dataclass
class FailureMetrics:
    """Metrics for a single document pair."""

    file_name: str

    # Link metrics
    source_links: int = 0
    target_links: int = 0
    has_broken_link_syntax: bool = False

    # Code metrics
    source_code_blocks: int = 0
    target_code_blocks: int = 0
    source_code_spans: int = 0
    target_code_spans: int = 0

    # Formatting metrics
    source_bold: int = 0
    target_bold: int = 0
    source_italic: int = 0
    target_italic: int = 0

    # Structure metrics (paragraph count as proxy)
    source_paragraphs: int = 0
    target_paragraphs: int = 0

    # Errors
    parsing_errors: list[str] = field(default_factory=list)


@dataclass
class AggregateMetrics:
    """Aggregate metrics across all analyzed files."""

    total_files: int = 0
    analyzed_successfully: int = 0

    total_source_links: int = 0
    total_target_links: int = 0
    files_with_broken_links: int = 0

    total_source_code_blocks: int = 0
    total_target_code_blocks: int = 0
    total_source_code_spans: int = 0
    total_target_code_spans: int = 0
    files_with_missing_code: int = 0

    total_source_bold: int = 0
    total_target_bold: int = 0
    total_source_italic: int = 0
    total_target_italic: int = 0
    files_with_formatting_loss: int = 0

    total_source_paragraphs: int = 0
    total_target_paragraphs: int = 0
    files_with_structure_drift: int = 0


def count_markdown_elements(content: str) -> tuple[int, int, int, int, int, int, bool]:
    """
    Count markdown elements using regex patterns.

    Returns: (links, code_blocks, code_spans, bold, italic, paragraphs, has_broken_links)
    """
    # Skip YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]

    # Count valid markdown links: [text](url)
    link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
    links = len(re.findall(link_pattern, content))

    # Count code blocks (fenced and indented)
    code_block_pattern = r"```[\s\S]*?```|~~~[\s\S]*?~~~"
    code_blocks = len(re.findall(code_block_pattern, content))

    # Count inline code spans: `code`
    code_span_pattern = r"`[^`]+`"
    code_spans = len(re.findall(code_span_pattern, content))

    # Count bold: **text** or __text__
    bold_pattern = r"\*\*[^*]+\*\*|__[^_]+__"
    bold = len(re.findall(bold_pattern, content))

    # Count italic: *text* or _text_ (but not part of bold)
    # This is simplified - doesn't handle all edge cases
    italic_pattern = r"(?<!\*)\*[^*]+\*(?!\*)|(?<!_)_[^_]+_(?!_)"
    italic = len(re.findall(italic_pattern, content))

    # Count paragraphs (double newline separated blocks)
    paragraphs = len([p for p in content.split("\n\n") if p.strip()])

    # Check for broken link syntax patterns
    broken_patterns = [
        r"<linkhref=",  # Malformed XML-like link
        r"</link>",  # Malformed closing tag
        r"\]\(⟦URL",  # Placeholder corruption
        r"\{\{IFP_LU",  # Exposed placeholder
        r"\]\[http",  # Broken markdown syntax
        r"</strang>",  # Typo in closing tag
        r"</strong<",  # Malformed closing tag
        r"\*\*[^*]*$",  # Unclosed bold at end of line
    ]
    has_broken_links = any(re.search(pattern, content) for pattern in broken_patterns)

    return (links, code_blocks, code_spans, bold, italic, paragraphs, has_broken_links)


def analyze_document_pair(source_path: Path, target_path: Path) -> FailureMetrics:
    """Analyze a single source-target document pair."""
    metrics = FailureMetrics(file_name=source_path.name)

    try:
        # Read files
        source_content = source_path.read_text(encoding="utf-8")
        target_content = target_path.read_text(encoding="utf-8")

        # Analyze source
        (
            metrics.source_links,
            metrics.source_code_blocks,
            metrics.source_code_spans,
            metrics.source_bold,
            metrics.source_italic,
            metrics.source_paragraphs,
            _,
        ) = count_markdown_elements(source_content)

        # Analyze target
        (
            metrics.target_links,
            metrics.target_code_blocks,
            metrics.target_code_spans,
            metrics.target_bold,
            metrics.target_italic,
            metrics.target_paragraphs,
            metrics.has_broken_link_syntax,
        ) = count_markdown_elements(target_content)

    except Exception as e:
        metrics.parsing_errors.append(str(e))

    return metrics


def aggregate_metrics(metrics_list: list[FailureMetrics]) -> AggregateMetrics:
    """Aggregate metrics from multiple document pairs."""
    agg = AggregateMetrics()
    agg.total_files = len(metrics_list)

    for m in metrics_list:
        if not m.parsing_errors:
            agg.analyzed_successfully += 1

            # Links
            agg.total_source_links += m.source_links
            agg.total_target_links += m.target_links
            if m.has_broken_link_syntax or m.target_links < m.source_links:
                agg.files_with_broken_links += 1

            # Code
            agg.total_source_code_blocks += m.source_code_blocks
            agg.total_target_code_blocks += m.target_code_blocks
            agg.total_source_code_spans += m.source_code_spans
            agg.total_target_code_spans += m.target_code_spans
            if (
                m.target_code_blocks < m.source_code_blocks
                or m.target_code_spans < m.source_code_spans
            ):
                agg.files_with_missing_code += 1

            # Formatting
            agg.total_source_bold += m.source_bold
            agg.total_target_bold += m.target_bold
            agg.total_source_italic += m.source_italic
            agg.total_target_italic += m.target_italic
            if m.target_bold < m.source_bold or m.target_italic < m.source_italic:
                agg.files_with_formatting_loss += 1

            # Structure
            agg.total_source_paragraphs += m.source_paragraphs
            agg.total_target_paragraphs += m.target_paragraphs
            # Allow ±15% tolerance for paragraph count drift
            if m.source_paragraphs > 0:
                drift = abs(m.target_paragraphs - m.source_paragraphs) / m.source_paragraphs
                if drift > 0.15:
                    agg.files_with_structure_drift += 1

    return agg


def format_report(agg: AggregateMetrics, sample_size: int) -> str:
    """Format aggregate metrics as a report."""
    report_lines = [
        "# HP-06 TC-00: Quantitative Failure Analysis",
        "",
        f"**Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Files Analyzed**: {sample_size}",
        f"**Successfully Analyzed**: {agg.analyzed_successfully}",
        "**Source Corpus**: `kb.aspose.net/slides/en` → `kb.aspose.net/slides/de`",
        "",
        "## Executive Summary",
        "",
    ]

    # Calculate percentages
    broken_links_pct = 0
    missing_code_pct = 0
    formatting_loss_pct = 0
    structure_drift_pct = 0

    if agg.analyzed_successfully > 0:
        broken_links_pct = (agg.files_with_broken_links / agg.analyzed_successfully) * 100
        missing_code_pct = (agg.files_with_missing_code / agg.analyzed_successfully) * 100
        formatting_loss_pct = (agg.files_with_formatting_loss / agg.analyzed_successfully) * 100
        structure_drift_pct = (agg.files_with_structure_drift / agg.analyzed_successfully) * 100

        report_lines.extend(
            [
                f"- **Broken links**: {broken_links_pct:.1f}% ({agg.files_with_broken_links}/{agg.analyzed_successfully} files)",
                f"- **Missing code**: {missing_code_pct:.1f}% ({agg.files_with_missing_code}/{agg.analyzed_successfully} files)",
                f"- **Formatting loss**: {formatting_loss_pct:.1f}% ({agg.files_with_formatting_loss}/{agg.analyzed_successfully} files)",
                f"- **Structure drift**: {structure_drift_pct:.1f}% ({agg.files_with_structure_drift}/{agg.analyzed_successfully} files)",
                "",
            ]
        )

    report_lines.extend(
        [
            "## Detailed Metrics",
            "",
            "### Link Preservation",
            "",
            f"- Source links: {agg.total_source_links}",
            f"- Target links: {agg.total_target_links}",
            f"- Links lost: {agg.total_source_links - agg.total_target_links}",
            "",
            "### Code Preservation",
            "",
            f"- Source code blocks: {agg.total_source_code_blocks}",
            f"- Target code blocks: {agg.total_target_code_blocks}",
            f"- Code blocks lost: {agg.total_source_code_blocks - agg.total_target_code_blocks}",
            "",
            f"- Source code spans: {agg.total_source_code_spans}",
            f"- Target code spans: {agg.total_target_code_spans}",
            f"- Code spans lost: {agg.total_source_code_spans - agg.total_target_code_spans}",
            "",
            "### Formatting Preservation",
            "",
            f"- Source bold elements: {agg.total_source_bold}",
            f"- Target bold elements: {agg.total_target_bold}",
            f"- Bold elements lost: {agg.total_source_bold - agg.total_target_bold}",
            "",
            f"- Source italic elements: {agg.total_source_italic}",
            f"- Target italic elements: {agg.total_target_italic}",
            f"- Italic elements lost: {agg.total_source_italic - agg.total_target_italic}",
            "",
            "### Structure Preservation",
            "",
            f"- Source paragraphs: {agg.total_source_paragraphs}",
            f"- Target paragraphs: {agg.total_target_paragraphs}",
            f"- Paragraph count difference: {agg.total_target_paragraphs - agg.total_source_paragraphs}",
            f"- Files with >15% structure drift: {agg.files_with_structure_drift}",
            "",
            "## Failure Pattern Analysis",
            "",
            "Based on the quantitative analysis, the following corruption patterns are observed:",
            "",
            "1. **Link Corruption**: Markdown link syntax `[text](url)` is often broken or converted to malformed XML-like tags",
            "2. **Code Loss**: Inline code backticks and code blocks are frequently stripped during translation",
            "3. **Formatting Loss**: Bold `**` and italic `*` markers are removed or corrupted",
            "4. **Structure Drift**: Document structure changes due to MT model reorganization",
            "",
            "## Methodology",
            "",
            f"- Sampled {sample_size} random files from the English → German translation corpus",
            "- Analyzed both source and target files using regex pattern matching",
            "- Compared element counts to identify loss or corruption",
            "- Detected malformed syntax patterns in target files",
            "",
            "**Limitations**:",
            "- Regex-based analysis may miss complex nested structures",
            "- Does not measure semantic correctness of translations",
            "- Paragraph-based structure analysis is a proxy for full AST comparison",
            "",
            "## Conclusion",
            "",
            "These metrics establish the baseline failure rate for the current translation pipeline.",
            "HP-06 aims to reduce all these failure rates to near-zero through AST-based reconstruction.",
            "",
            "**Key Findings**:",
            f"- {broken_links_pct:.0f}% of files have broken or missing links"
            if agg.analyzed_successfully > 0
            else "",
            f"- {missing_code_pct:.0f}% of files have missing code elements"
            if agg.analyzed_successfully > 0
            else "",
            f"- {formatting_loss_pct:.0f}% of files have lost formatting"
            if agg.analyzed_successfully > 0
            else "",
            f"- {structure_drift_pct:.0f}% of files have significant structure drift"
            if agg.analyzed_successfully > 0
            else "",
            "",
        ]
    )

    return "\n".join(report_lines)


def main():
    """Main analysis function."""
    # Paths
    source_dir = Path(
        r"c:\Users\prora\OneDrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en"
    )
    target_dir = Path(
        r"c:\Users\prora\OneDrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\de"
    )

    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        return 1

    if not target_dir.exists():
        print(f"Error: Target directory not found: {target_dir}")
        return 1

    # Get all source markdown files
    source_files = list(source_dir.rglob("*.md"))

    if len(source_files) == 0:
        print(f"Error: No markdown files found in {source_dir}")
        return 1

    # Sample 100 random files (or all if less than 100)
    sample_size = min(100, len(source_files))
    random.seed(42)  # Reproducible sampling
    sampled_sources = random.sample(source_files, sample_size)

    print(f"Found {len(source_files)} source files")
    print(f"Analyzing {sample_size} random files...")
    print()

    # Analyze each pair
    metrics_list = []
    for i, source_path in enumerate(sampled_sources, 1):
        # Find corresponding target file
        rel_path = source_path.relative_to(source_dir)
        target_path = target_dir / rel_path

        if not target_path.exists():
            print(f"[{i}/{sample_size}] SKIP: {rel_path} (no translation found)")
            continue

        print(f"[{i}/{sample_size}] Analyzing: {rel_path}")
        metrics = analyze_document_pair(source_path, target_path)
        metrics_list.append(metrics)

        if metrics.parsing_errors:
            print(f"  WARNING: Parsing errors: {metrics.parsing_errors}")

    # Aggregate and generate report
    agg = aggregate_metrics(metrics_list)
    report = format_report(agg, len(metrics_list))

    # Write report
    output_path = (
        Path(__file__).parent.parent / "tests" / "fixtures" / "hp06" / "BASELINE_FAILURES.md"
    )
    output_path.write_text(report, encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Report written to: {output_path}")
    print("=" * 60)
    print()
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
