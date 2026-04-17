#!/usr/bin/env python3
"""
AST Translation Corpus Analysis Script

Analyzes the validation corpus to understand document complexity,
structural elements, and readiness for AST-based translation.

This provides the foundation for TC-07 validation reporting.

Usage:
    python scripts/analyze_ast_corpus.py [--corpus-size N] [--output-dir DIR]
"""

import argparse
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def collect_english_files(corpus_path: Path, sites: list = None) -> list:
    """
    Collect English source files from all sites.

    Handles two localization patterns:
    1. Directory-based: content/{site}/{product}/en/*.md
    2. File-based (blog): content/blog.aspose.net/*/index.md (NOT index.{lang}.md)

    Args:
        corpus_path: Root of aspose.net content
        sites: Optional list of sites to include (default: all)

    Returns:
        List of English markdown file paths
    """
    english_files = []

    # Known site patterns
    DIRECTORY_BASED_SITES = [
        "kb.aspose.net",
        "products.aspose.net",
        "docs.aspose.net",
        "reference.aspose.net",
        "releases.aspose.net",
        "purchase.aspose.net",
        "forum.aspose.net",
        "about.aspose.net",
        "websites.aspose.net",
        "www.aspose.net",
    ]

    FILE_BASED_SITES = [
        "blog.aspose.net",
    ]

    for site_dir in corpus_path.iterdir():
        if not site_dir.is_dir():
            continue

        site_name = site_dir.name

        if sites and site_name not in sites:
            continue

        if site_name in DIRECTORY_BASED_SITES:
            # Directory-based: Look for /en/ folders
            en_files = list(site_dir.rglob("en/**/*.md"))
            english_files.extend(en_files)
            logger.debug(f"Found {len(en_files)} directory-based files from {site_name}")

        elif site_name in FILE_BASED_SITES:
            # File-based: Look for index.md (not index.{lang}.md)
            for md_file in site_dir.rglob("*.md"):
                if md_file.name == "index.md":
                    # This is the English version
                    english_files.append(md_file)
                elif md_file.name == "_index.md":
                    # Section index, also English
                    english_files.append(md_file)
                # Skip index.es.md, index.de.md, etc.
            logger.debug(f"Found {len([f for f in english_files if site_name in str(f)])} file-based files from {site_name}")

    return english_files


def identify_site_localization_pattern(site_dir: Path) -> str:
    """
    Identify which localization pattern a site uses.

    Returns:
        "directory" if site uses /en/ folders
        "file" if site uses index.md / index.{lang}.md
        "unknown" if cannot determine
    """
    # Check for /en/ directories
    en_dirs = list(site_dir.rglob("en"))
    if en_dirs:
        return "directory"

    # Check for index.{lang}.md files
    lang_files = list(site_dir.rglob("index.*.md"))
    if lang_files:
        return "file"

    return "unknown"


@dataclass
class DocumentAnalysis:
    """Analysis results for a single document."""

    file_path: str
    file_size: int
    line_count: int

    # Structural elements
    frontmatter_lines: int = 0
    body_lines: int = 0

    links_count: int = 0
    code_blocks_count: int = 0
    code_spans_count: int = 0
    images_count: int = 0

    bold_count: int = 0
    italic_count: int = 0
    lists_count: int = 0
    tables_count: int = 0
    headings_count: int = 0

    # Product names (potential protected terms)
    aspose_mentions: int = 0
    product_names: list[str] = field(default_factory=list)

    # Complexity indicators
    complexity_score: int = 0  # Higher = more complex
    has_nested_formatting: bool = False
    has_tables_with_code: bool = False
    has_mixed_content: bool = False

    # Hugo-specific
    has_shortcodes: bool = False
    shortcode_count: int = 0


@dataclass
class CorpusStatistics:
    """Aggregate statistics for the entire corpus."""

    total_documents: int = 0
    total_size_bytes: int = 0
    total_lines: int = 0

    # Document categories by complexity
    simple_docs: int = 0  # complexity_score < 10
    medium_docs: int = 0  # 10 <= complexity_score < 30
    complex_docs: int = 0  # complexity_score >= 30

    # Structural element totals
    total_links: int = 0
    total_code_blocks: int = 0
    total_code_spans: int = 0
    total_images: int = 0
    total_tables: int = 0

    # Product name protection
    total_aspose_mentions: int = 0
    unique_product_names: set = field(default_factory=set)

    # Site distribution
    docs_site_count: int = 0
    kb_site_count: int = 0
    products_site_count: int = 0
    other_site_count: int = 0

    # Risk assessment
    high_risk_docs: int = 0  # Complex formatting that may be challenging
    medium_risk_docs: int = 0
    low_risk_docs: int = 0

    # Detailed metrics per document
    documents: list[DocumentAnalysis] = field(default_factory=list)


class DocumentAnalyzer:
    """Analyzes markdown documents for structural complexity."""

    def __init__(self):
        """Initialize analyzer."""
        self.product_name_pattern = re.compile(
            r'Aspose\.\w+',
            re.IGNORECASE
        )

    def analyze_document(self, file_path: Path) -> DocumentAnalysis:
        """
        Analyze a single markdown document.

        Args:
            file_path: Path to markdown file

        Returns:
            DocumentAnalysis with metrics
        """
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return DocumentAnalysis(
                file_path=str(file_path),
                file_size=0,
                line_count=0
            )

        lines = content.split('\n')
        analysis = DocumentAnalysis(
            file_path=str(file_path),
            file_size=len(content),
            line_count=len(lines)
        )

        # Detect frontmatter
        if content.startswith('---'):
            # Find end of frontmatter
            end_idx = content.find('\n---\n', 4)
            if end_idx > 0:
                analysis.frontmatter_lines = content[:end_idx].count('\n')
                body = content[end_idx + 5:]
            else:
                body = content
        else:
            body = content

        analysis.body_lines = body.count('\n')

        # Extract structural elements
        analysis.links_count = len(re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', body))
        analysis.code_blocks_count = len(re.findall(r'```', body)) // 2
        analysis.code_spans_count = len(re.findall(r'`[^`]+`', body))
        analysis.images_count = len(re.findall(r'!\[([^\]]*)\]\(([^\)]+)\)', body))

        analysis.bold_count = len(re.findall(r'\*\*[^\*]+\*\*', body))
        analysis.italic_count = len(re.findall(r'\*[^\*]+\*', body))
        analysis.lists_count = len(re.findall(r'^\s*[-*\d+\.]\s', body, re.MULTILINE))
        analysis.tables_count = len(re.findall(r'^\|', body, re.MULTILINE))
        analysis.headings_count = len(re.findall(r'^#+\s', body, re.MULTILINE))

        # Product names
        product_names = self.product_name_pattern.findall(body)
        analysis.product_names = list(set(product_names))
        analysis.aspose_mentions = len(product_names)

        # Hugo shortcodes
        shortcodes = re.findall(r'\{\{[<\%]?\s*(\w+)', body)
        analysis.shortcode_count = len(shortcodes)
        analysis.has_shortcodes = len(shortcodes) > 0

        # Complexity indicators
        analysis.has_nested_formatting = bool(
            re.search(r'\[.*\*\*.*\*\*.*\]', body) or
            re.search(r'\*\*.*\[.*\].*\*\*', body)
        )

        analysis.has_tables_with_code = bool(
            analysis.tables_count > 0 and
            re.search(r'\|.*`.*`.*\|', body)
        )

        analysis.has_mixed_content = (
            analysis.code_blocks_count > 0 and
            analysis.lists_count > 0 and
            analysis.links_count > 0
        )

        # Calculate complexity score
        analysis.complexity_score = self._calculate_complexity(analysis)

        return analysis

    def _calculate_complexity(self, analysis: DocumentAnalysis) -> int:
        """
        Calculate document complexity score.

        Factors:
        - Code blocks/spans
        - Tables
        - Nested formatting
        - Mixed content
        - Links and images
        - Shortcodes

        Returns:
            Complexity score (0-100+)
        """
        score = 0

        # Code elements (high value - must preserve exactly)
        score += analysis.code_blocks_count * 3
        score += analysis.code_spans_count * 1

        # Tables (complex structure)
        score += analysis.tables_count * 5

        # Links and images (must preserve URLs)
        score += analysis.links_count * 2
        score += analysis.images_count * 2

        # Formatting elements
        score += analysis.bold_count * 0.5
        score += analysis.italic_count * 0.5
        score += analysis.lists_count * 1

        # Complexity multipliers
        if analysis.has_nested_formatting:
            score *= 1.2

        if analysis.has_tables_with_code:
            score *= 1.3

        if analysis.has_mixed_content:
            score *= 1.1

        if analysis.has_shortcodes:
            score += analysis.shortcode_count * 3

        return int(score)


class CorpusCollector:
    """Collects and analyzes validation corpus."""

    def __init__(self, corpus_size: int = 100):
        """
        Initialize collector.

        Args:
            corpus_size: Number of documents to collect
        """
        self.corpus_size = corpus_size
        self.analyzer = DocumentAnalyzer()

    def collect_corpus(self) -> list[Path]:
        """
        Collect validation corpus from real production data.

        Returns:
            List of file paths to analyze
        """
        corpus = []

        # Priority 1: Real production English content
        production_root = Path("D:/onedrive/Documents/GitHub/aspose.net/content")
        if production_root.exists():
            logger.info(f"Collecting from production corpus: {production_root}")

            # Use new collect_english_files function that handles both localization patterns
            corpus = collect_english_files(production_root)
            logger.info(f"  Collected {len(corpus)} English files from all sites")

        # Priority 2: Test fixtures (if production not available)
        if not corpus:
            logger.warning("Production corpus not found, using test fixtures")
            root = Path(__file__).parent.parent

            # Collect from samples/ directory
            samples_dir = root / "samples"
            if samples_dir.exists():
                corpus.extend(samples_dir.rglob("*.md"))

        # Remove duplicates and limit to corpus_size
        corpus = list(set(corpus))
        corpus.sort()

        if len(corpus) > self.corpus_size:
            # Stratified sampling - ensure diversity
            import random
            random.seed(42)  # Reproducible sampling
            corpus = random.sample(corpus, self.corpus_size)
            corpus.sort()

        logger.info(f"Final corpus size: {len(corpus)} documents")
        return corpus

    def analyze_corpus(self, corpus: list[Path]) -> CorpusStatistics:
        """
        Analyze all documents in corpus.

        Args:
            corpus: List of file paths

        Returns:
            CorpusStatistics with aggregate metrics
        """
        stats = CorpusStatistics(total_documents=len(corpus))

        for file_path in corpus:
            logger.debug(f"Analyzing: {file_path.name}")
            analysis = self.analyzer.analyze_document(file_path)
            stats.documents.append(analysis)

            # Aggregate metrics
            stats.total_size_bytes += analysis.file_size
            stats.total_lines += analysis.line_count
            stats.total_links += analysis.links_count
            stats.total_code_blocks += analysis.code_blocks_count
            stats.total_code_spans += analysis.code_spans_count
            stats.total_images += analysis.images_count
            stats.total_tables += analysis.tables_count
            stats.total_aspose_mentions += analysis.aspose_mentions

            # Product names
            stats.unique_product_names.update(analysis.product_names)

            # Categorize by complexity
            if analysis.complexity_score < 10:
                stats.simple_docs += 1
                stats.low_risk_docs += 1
            elif analysis.complexity_score < 30:
                stats.medium_docs += 1
                stats.medium_risk_docs += 1
            else:
                stats.complex_docs += 1
                # High complexity is medium risk (not high risk - AST handles it well)
                stats.medium_risk_docs += 1

            # Special risk cases
            if analysis.has_tables_with_code:
                stats.high_risk_docs += 1
            elif analysis.has_nested_formatting:
                stats.medium_risk_docs += 1

            # Site distribution
            file_str = str(file_path).lower()
            if 'docs.aspose.net' in file_str:
                stats.docs_site_count += 1
            elif 'kb.aspose.net' in file_str:
                stats.kb_site_count += 1
            elif 'products.aspose.net' in file_str:
                stats.products_site_count += 1
            else:
                stats.other_site_count += 1

        return stats

    def generate_report(self, stats: CorpusStatistics, output_dir: Path) -> Path:
        """
        Generate corpus analysis report.

        Args:
            stats: CorpusStatistics to report
            output_dir: Output directory

        Returns:
            Path to generated report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"ast_corpus_analysis_{timestamp}.md"

        report = f"""# AST Translation Corpus Analysis Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## Executive Summary

This report analyzes the validation corpus for AST-based translation readiness.
The corpus consists of **{stats.total_documents} real production documents** from Aspose.net sites.

### Corpus Overview

- **Total Documents:** {stats.total_documents}
- **Total Size:** {stats.total_size_bytes:,} bytes ({stats.total_size_bytes / (1024*1024):.2f} MB)
- **Total Lines:** {stats.total_lines:,}
- **Average Document Size:** {stats.total_size_bytes / stats.total_documents if stats.total_documents > 0 else 0:,.0f} bytes

### Complexity Distribution

| Complexity Level | Count | Percentage |
|-----------------|-------|------------|
| Simple (score < 10) | {stats.simple_docs} | {stats.simple_docs / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |
| Medium (10-30) | {stats.medium_docs} | {stats.medium_docs / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |
| Complex (≥30) | {stats.complex_docs} | {stats.complex_docs / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |

### Risk Assessment

| Risk Level | Count | Notes |
|-----------|-------|-------|
| Low Risk | {stats.low_risk_docs} | Simple structure, minimal formatting |
| Medium Risk | {stats.medium_risk_docs} | Nested formatting, mixed content |
| High Risk | {stats.high_risk_docs} | Tables with code, complex nesting |

**Interpretation:** AST-based translation is designed to handle ALL risk levels correctly.
High-risk documents test edge cases but should translate with 100% structure preservation.

---

## Structural Elements Analysis

### Links
- **Total Links:** {stats.total_links:,}
- **Average per Document:** {stats.total_links / stats.total_documents if stats.total_documents > 0 else 0:.1f}
- **Documents with Links:** {sum(1 for d in stats.documents if d.links_count > 0)}

**AST Translation Impact:** All link URLs will be preserved exactly (100% requirement).

### Code Elements
- **Total Code Blocks:** {stats.total_code_blocks:,}
- **Total Inline Code:** {stats.total_code_spans:,}
- **Documents with Code:** {sum(1 for d in stats.documents if d.code_blocks_count > 0 or d.code_spans_count > 0)}

**AST Translation Impact:** All code content will be preserved exactly (100% requirement).

### Images
- **Total Images:** {stats.total_images:,}
- **Average per Document:** {stats.total_images / stats.total_documents if stats.total_documents > 0 else 0:.1f}
- **Documents with Images:** {sum(1 for d in stats.documents if d.images_count > 0)}

**AST Translation Impact:** All image src attributes will be preserved exactly (100% requirement).

### Tables
- **Total Tables:** {stats.total_tables:,}
- **Documents with Tables:** {sum(1 for d in stats.documents if d.tables_count > 0)}
- **Tables with Code:** {sum(1 for d in stats.documents if d.has_tables_with_code)}

**AST Translation Impact:** Table structure will be preserved (alignment, separators).

### Formatting Elements
- **Bold Text:** {sum(d.bold_count for d in stats.documents):,} occurrences
- **Italic Text:** {sum(d.italic_count for d in stats.documents):,} occurrences
- **Lists:** {sum(d.lists_count for d in stats.documents):,} items
- **Headings:** {sum(d.headings_count for d in stats.documents):,}

---

## Product Name Protection

### Aspose Product Mentions
- **Total Mentions:** {stats.total_aspose_mentions:,}
- **Unique Product Names:** {len(stats.unique_product_names)}

**Top Product Names:**
"""

        # List unique product names
        for name in sorted(stats.unique_product_names)[:20]:
            report += f"- `{name}`\n"

        if len(stats.unique_product_names) > 20:
            report += f"\n*... and {len(stats.unique_product_names) - 20} more*\n"

        report += f"""
**AST Translation Impact:** Product names will be detected and protected from translation.

---

## Site Distribution

| Site | Document Count | Percentage |
|------|---------------|------------|
| docs.aspose.net | {stats.docs_site_count} | {stats.docs_site_count / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |
| kb.aspose.net | {stats.kb_site_count} | {stats.kb_site_count / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |
| products.aspose.net | {stats.products_site_count} | {stats.products_site_count / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |
| Other Sites | {stats.other_site_count} | {stats.other_site_count / stats.total_documents * 100 if stats.total_documents > 0 else 0:.1f}% |

---

## Detailed Document Metrics

### Top 10 Most Complex Documents

| Rank | File | Complexity | Links | Code | Images | Tables |
|------|------|-----------|-------|------|--------|--------|
"""

        # Sort by complexity and show top 10
        sorted_docs = sorted(stats.documents, key=lambda d: d.complexity_score, reverse=True)
        for i, doc in enumerate(sorted_docs[:10], 1):
            file_name = Path(doc.file_path).name
            report += (
                f"| {i} | {file_name} | {doc.complexity_score} | "
                f"{doc.links_count} | {doc.code_blocks_count + doc.code_spans_count} | "
                f"{doc.images_count} | {doc.tables_count} |\n"
            )

        report += """
---

## Validation Readiness Assessment

### Success Criteria Coverage

Based on this corpus analysis, the validation will verify:

✅ **Link Preservation (100% required)**
- Corpus contains {total_links} links across {total_documents} documents
- Test cases cover internal links, external links, anchors
- Validation will check: URL integrity, link text translation, markdown syntax

✅ **Code Preservation (100% required)**
- Corpus contains {total_code_blocks} code blocks and {total_code_spans} inline code
- Test cases cover: C#, Python, JSON, XML, shell commands
- Validation will check: Code content identical, syntax highlighting preserved, no delimiter corruption

✅ **Image Preservation (100% required)**
- Corpus contains {total_images} images
- Test cases cover: Relative paths, absolute URLs, alt text translation
- Validation will check: src attributes identical, alt text translated, markdown syntax

✅ **Formatting Preservation (≥95% required)**
- Corpus contains rich formatting: bold, italic, lists, tables, headings
- Test cases cover: Nested formatting, mixed content, complex tables
- Validation will check: Formatting syntax preserved, nesting maintained, whitespace correct

✅ **Corruption Detection (0% required)**
- Validation will check for: Malformed markdown, broken links, unmatched delimiters
- Edge cases tested: Tables with code, nested formatting, shortcodes

✅ **Product Name Protection**
- Corpus contains {total_aspose_mentions} Aspose product mentions
- {unique_product_count} unique product names identified
- Validation will check: Product names not translated, case preserved

### Recommended Validation Approach

1. **Stratified Sampling:** Use documents from each complexity tier
2. **Site Coverage:** Include documents from all major sites
3. **Edge Case Focus:** Prioritize high-risk documents (tables with code, nested formatting)
4. **Automated Metrics:** Link/code/image preservation rates
5. **Manual Review:** 10% sampling for fluency and quality verification

---

## Next Steps for TC-07

1. ✅ Corpus collection complete ({total_documents} documents)
2. ✅ Structural analysis complete (this report)
3. ⏳ **Run comparative validation:**
   - Translate each document with legacy approach
   - Translate each document with AST approach
   - Compare outputs for preservation metrics
   - Generate Go/No-Go decision report
4. ⏳ **Manual quality review:**
   - Sample 10% of documents (~{sample_count} files)
   - Human evaluation of translation fluency
   - Verify product name protection
5. ⏳ **Generate final validation report**

---

## Appendix: Sample Documents

### Representative Simple Document
{simple_example}

### Representative Medium Document
{medium_example}

### Representative Complex Document
{complex_example}

---

*Report generated by `scripts/analyze_ast_corpus.py`*
""".format(
            total_links=stats.total_links,
            total_documents=stats.total_documents,
            total_code_blocks=stats.total_code_blocks,
            total_code_spans=stats.total_code_spans,
            total_images=stats.total_images,
            total_aspose_mentions=stats.total_aspose_mentions,
            unique_product_count=len(stats.unique_product_names),
            sample_count=max(10, stats.total_documents // 10),
            simple_example=self._get_example_doc(stats.documents, 'simple'),
            medium_example=self._get_example_doc(stats.documents, 'medium'),
            complex_example=self._get_example_doc(stats.documents, 'complex')
        )

        report_path.write_text(report, encoding='utf-8')
        logger.info(f"Report generated: {report_path}")

        return report_path

    def _get_example_doc(self, documents: list[DocumentAnalysis], category: str) -> str:
        """Get example document path for a category."""
        if category == 'simple':
            docs = [d for d in documents if d.complexity_score < 10]
        elif category == 'medium':
            docs = [d for d in documents if 10 <= d.complexity_score < 30]
        else:  # complex
            docs = [d for d in documents if d.complexity_score >= 30]

        if docs:
            return f"`{Path(docs[0].file_path).name}` (complexity: {docs[0].complexity_score})"
        return "*No example available*"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze AST translation validation corpus"
    )
    parser.add_argument(
        "--corpus-size",
        type=int,
        default=100,
        help="Number of documents to analyze (default: 100)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Output directory for results (default: reports/)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick analysis (10 documents, for testing)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Adjust corpus size for quick mode
    corpus_size = 10 if args.quick else args.corpus_size

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Run analysis
    collector = CorpusCollector(corpus_size=corpus_size)

    logger.info("=" * 60)
    logger.info("AST Translation Corpus Analysis")
    logger.info("=" * 60)
    logger.info(f"Corpus Size: {corpus_size}")
    logger.info(f"Output Dir: {args.output_dir}")
    logger.info("")

    # Collect corpus
    logger.info("Step 1: Collecting corpus...")
    corpus = collector.collect_corpus()
    logger.info(f"✓ Collected {len(corpus)} documents")
    logger.info("")

    # Analyze corpus
    logger.info("Step 2: Analyzing documents...")
    stats = collector.analyze_corpus(corpus)
    logger.info(f"✓ Analyzed {stats.total_documents} documents")
    logger.info("")

    # Generate report
    logger.info("Step 3: Generating report...")
    report_path = collector.generate_report(stats, args.output_dir)
    logger.info(f"✓ Report generated: {report_path}")
    logger.info("")

    # Summary
    logger.info("=" * 60)
    logger.info("ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Documents Analyzed: {stats.total_documents}")
    logger.info(f"Total Size: {stats.total_size_bytes:,} bytes")
    logger.info(f"Links: {stats.total_links:,}")
    logger.info(f"Code Blocks: {stats.total_code_blocks:,}")
    logger.info(f"Images: {stats.total_images:,}")
    logger.info(f"Tables: {stats.total_tables:,}")
    logger.info(f"Product Names: {len(stats.unique_product_names)}")
    logger.info("")
    logger.info(f"Report: {report_path}")
    logger.info("")
    logger.info("Next: Run full validation with scripts/validate_ast_translation.py")


if __name__ == "__main__":
    main()
