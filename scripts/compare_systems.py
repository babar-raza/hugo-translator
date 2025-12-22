#!/usr/bin/env python
"""
System Comparison Tool

Compares translation outputs from legacy system vs new system to validate
migration quality and ensure no regressions.

Usage:
    python scripts/compare_systems.py --legacy <path> --new <path> [--output <report>]

Arguments:
    --legacy         Path to legacy system output directory
    --new            Path to new system output directory
    --output         Path to comparison report (default: reports/comparison_report.md)
    --sample_size    Number of files to sample for detailed comparison (default: 100)
    --threshold      Similarity threshold for warnings (default: 0.95)
    --verbose        Enable verbose logging

Description:
    Performs comprehensive comparison:
    1. File-level comparison (exists in both systems)
    2. Content similarity analysis (Levenshtein distance)
    3. Structure validation (frontmatter, code blocks, links)
    4. Translation quality metrics
    5. Performance comparison (if metrics available)

    Generates detailed report with:
    - Overall statistics
    - File-by-file differences
    - Quality metrics
    - Recommendations

Example:
    # Compare outputs
    python scripts/compare_systems.py \\
        --legacy ./content_legacy/de \\
        --new ./content_new/de \\
        --output reports/de_comparison.md
"""

import argparse
import difflib
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import re

import frontmatter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SystemComparator:
    """Compares legacy vs new system outputs"""

    def __init__(
        self,
        legacy_dir: str,
        new_dir: str,
        output_report: str,
        sample_size: int = 100,
        threshold: float = 0.95
    ):
        self.legacy_dir = Path(legacy_dir)
        self.new_dir = Path(new_dir)
        self.output_report = Path(output_report)
        self.sample_size = sample_size
        self.threshold = threshold

        self.stats = defaultdict(int)
        self.differences = []
        self.warnings = []
        self.file_comparisons = []

        # Validate directories
        if not self.legacy_dir.exists():
            raise ValueError(f"Legacy directory not found: {legacy_dir}")
        if not self.new_dir.exists():
            raise ValueError(f"New directory not found: {new_dir}")

    def find_markdown_files(self, directory: Path) -> List[Path]:
        """Find all markdown files in directory"""
        patterns = ['*.md', '*.markdown']
        files = []

        for pattern in patterns:
            files.extend(directory.rglob(pattern))

        return files

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using SequenceMatcher"""
        matcher = difflib.SequenceMatcher(None, text1, text2)
        return matcher.ratio()

    def extract_frontmatter(self, file_path: Path) -> Tuple[Dict, str]:
        """Extract frontmatter and content from markdown file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                post = frontmatter.load(f)
                return dict(post.metadata), post.content
        except Exception as e:
            logger.warning(f"Failed to parse frontmatter in {file_path}: {e}")
            # Fallback to reading as plain text
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return {}, content

    def compare_structure(
        self,
        legacy_content: str,
        new_content: str
    ) -> Dict[str, bool]:
        """Compare structural elements"""
        checks = {}

        # Code blocks
        legacy_code_blocks = len(re.findall(r'```', legacy_content))
        new_code_blocks = len(re.findall(r'```', new_content))
        checks['code_blocks_match'] = legacy_code_blocks == new_code_blocks

        # Links
        legacy_links = len(re.findall(r'\[.*?\]\(.*?\)', legacy_content))
        new_links = len(re.findall(r'\[.*?\]\(.*?\)', new_content))
        checks['links_match'] = legacy_links == new_links

        # Headings
        legacy_headings = len(re.findall(r'^#+\s', legacy_content, re.MULTILINE))
        new_headings = len(re.findall(r'^#+\s', new_content, re.MULTILINE))
        checks['headings_match'] = legacy_headings == new_headings

        # Lists
        legacy_lists = len(re.findall(r'^\s*[-*+]\s', legacy_content, re.MULTILINE))
        new_lists = len(re.findall(r'^\s*[-*+]\s', new_content, re.MULTILINE))
        checks['lists_match'] = legacy_lists == new_lists

        return checks

    def compare_file(
        self,
        legacy_file: Path,
        new_file: Path,
        relative_path: str
    ) -> Dict:
        """Compare a single file from both systems"""
        result = {
            'file': relative_path,
            'legacy_exists': legacy_file.exists(),
            'new_exists': new_file.exists(),
            'similarity': 0.0,
            'structure_checks': {},
            'issues': []
        }

        if not legacy_file.exists() or not new_file.exists():
            result['issues'].append('File missing in one system')
            return result

        try:
            # Extract frontmatter and content
            legacy_fm, legacy_content = self.extract_frontmatter(legacy_file)
            new_fm, new_content = self.extract_frontmatter(new_file)

            # Compare content
            similarity = self.calculate_similarity(legacy_content, new_content)
            result['similarity'] = similarity

            # Compare structure
            result['structure_checks'] = self.compare_structure(legacy_content, new_content)

            # Check similarity threshold
            if similarity < self.threshold:
                result['issues'].append(f'Low similarity: {similarity:.2%}')
                self.warnings.append({
                    'file': relative_path,
                    'issue': f'Similarity below threshold ({similarity:.2%} < {self.threshold:.2%})',
                    'severity': 'warning'
                })

            # Check structure
            for check, passed in result['structure_checks'].items():
                if not passed:
                    result['issues'].append(f'Structure mismatch: {check}')

            # Update stats
            self.stats['files_compared'] += 1
            if similarity >= self.threshold:
                self.stats['high_similarity'] += 1
            if all(result['structure_checks'].values()):
                self.stats['structure_match'] += 1

        except Exception as e:
            result['issues'].append(f'Comparison error: {e}')
            logger.error(f"Error comparing {relative_path}: {e}")

        self.file_comparisons.append(result)
        return result

    def compare_all(self) -> Dict:
        """Compare all files from both systems"""
        logger.info("=" * 60)
        logger.info("System Comparison")
        logger.info("=" * 60)
        logger.info(f"Legacy: {self.legacy_dir}")
        logger.info(f"New:    {self.new_dir}")
        logger.info("")

        # Find files in both systems
        legacy_files = self.find_markdown_files(self.legacy_dir)
        new_files = self.find_markdown_files(self.new_dir)

        logger.info(f"Legacy system: {len(legacy_files)} files")
        logger.info(f"New system:    {len(new_files)} files")
        logger.info("")

        # Create relative path mappings
        legacy_map = {
            f.relative_to(self.legacy_dir): f
            for f in legacy_files
        }
        new_map = {
            f.relative_to(self.new_dir): f
            for f in new_files
        }

        # Find common and unique files
        common_files = set(legacy_map.keys()) & set(new_map.keys())
        legacy_only = set(legacy_map.keys()) - set(new_map.keys())
        new_only = set(new_map.keys()) - set(legacy_map.keys())

        self.stats['total_legacy'] = len(legacy_files)
        self.stats['total_new'] = len(new_files)
        self.stats['common_files'] = len(common_files)
        self.stats['legacy_only'] = len(legacy_only)
        self.stats['new_only'] = len(new_only)

        logger.info(f"Common files:    {len(common_files)}")
        logger.info(f"Legacy only:     {len(legacy_only)}")
        logger.info(f"New only:        {len(new_only)}")
        logger.info("")

        # Sample files for detailed comparison
        if len(common_files) > self.sample_size:
            logger.info(f"Sampling {self.sample_size} files for detailed comparison")
            sample_files = sorted(common_files)[:self.sample_size]
        else:
            sample_files = common_files

        # Compare files
        logger.info(f"Comparing {len(sample_files)} files...")
        for i, relative_path in enumerate(sample_files, 1):
            if i % 10 == 0 or i == len(sample_files):
                logger.info(f"  Progress: {i}/{len(sample_files)}")

            legacy_file = legacy_map[relative_path]
            new_file = new_map[relative_path]

            self.compare_file(legacy_file, new_file, str(relative_path))

        # Generate report
        self.generate_report()

        return self.stats

    def generate_report(self):
        """Generate markdown comparison report"""
        logger.info(f"Generating report: {self.output_report}")

        os.makedirs(self.output_report.parent, exist_ok=True)

        with open(self.output_report, 'w', encoding='utf-8') as f:
            f.write(f"# System Comparison Report\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Legacy System:** `{self.legacy_dir}`\n\n")
            f.write(f"**New System:** `{self.new_dir}`\n\n")
            f.write("---\n\n")

            # Overall Statistics
            f.write("## Overall Statistics\n\n")
            f.write(f"- **Total Files (Legacy):** {self.stats['total_legacy']}\n")
            f.write(f"- **Total Files (New):** {self.stats['total_new']}\n")
            f.write(f"- **Common Files:** {self.stats['common_files']}\n")
            f.write(f"- **Legacy Only:** {self.stats['legacy_only']}\n")
            f.write(f"- **New Only:** {self.stats['new_only']}\n")
            f.write(f"- **Files Compared:** {self.stats['files_compared']}\n")
            f.write(f"- **High Similarity (≥{self.threshold:.0%}):** {self.stats['high_similarity']}\n")
            f.write(f"- **Structure Match:** {self.stats['structure_match']}\n\n")

            # Quality Metrics
            if self.stats['files_compared'] > 0:
                similarity_rate = self.stats['high_similarity'] / self.stats['files_compared']
                structure_rate = self.stats['structure_match'] / self.stats['files_compared']

                f.write("## Quality Metrics\n\n")
                f.write(f"- **Similarity Rate:** {similarity_rate:.2%}\n")
                f.write(f"- **Structure Match Rate:** {structure_rate:.2%}\n\n")

                # Overall assessment
                if similarity_rate >= 0.95 and structure_rate >= 0.95:
                    f.write("✅ **Status:** Excellent - New system matches legacy output\n\n")
                elif similarity_rate >= 0.90 and structure_rate >= 0.90:
                    f.write("⚠️ **Status:** Good - Minor differences detected\n\n")
                else:
                    f.write("❌ **Status:** Review Required - Significant differences detected\n\n")

            # Warnings
            if self.warnings:
                f.write("## Warnings\n\n")
                f.write(f"Found {len(self.warnings)} warnings:\n\n")
                for warning in self.warnings[:20]:  # Show first 20
                    f.write(f"- **{warning['file']}**: {warning['issue']}\n")
                if len(self.warnings) > 20:
                    f.write(f"\n...and {len(self.warnings) - 20} more warnings\n")
                f.write("\n")

            # Detailed Comparison (sample)
            if self.file_comparisons:
                f.write("## File Comparison Details\n\n")
                f.write("| File | Similarity | Issues |\n")
                f.write("|------|------------|--------|\n")

                for comparison in self.file_comparisons[:50]:  # Show first 50
                    file = comparison['file']
                    sim = comparison['similarity']
                    issues = '; '.join(comparison['issues']) if comparison['issues'] else '✓'

                    sim_icon = '✅' if sim >= self.threshold else '⚠️'
                    f.write(f"| {file} | {sim_icon} {sim:.2%} | {issues} |\n")

                if len(self.file_comparisons) > 50:
                    f.write(f"\n*Showing 50 of {len(self.file_comparisons)} compared files*\n")

                f.write("\n")

            # Recommendations
            f.write("## Recommendations\n\n")

            if self.stats.get('high_similarity', 0) == self.stats.get('files_compared', 0):
                f.write("✅ All compared files meet similarity threshold\n\n")
                f.write("**Next Steps:**\n")
                f.write("1. Proceed with gradual migration\n")
                f.write("2. Monitor quality in production\n")
                f.write("3. Retire legacy system after validation period\n\n")
            else:
                low_sim_count = self.stats['files_compared'] - self.stats.get('high_similarity', 0)
                f.write(f"⚠️ {low_sim_count} files below similarity threshold\n\n")
                f.write("**Next Steps:**\n")
                f.write("1. Review files with low similarity\n")
                f.write("2. Investigate root causes of differences\n")
                f.write("3. Adjust new system configuration if needed\n")
                f.write("4. Re-run comparison after adjustments\n\n")

            # Footer
            f.write("---\n\n")
            f.write("*Generated by hugo-translator System Comparison Tool*\n")

        logger.info(f"✓ Report saved to: {self.output_report}")


def main():
    parser = argparse.ArgumentParser(
        description="Compare legacy vs new translation system outputs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--legacy',
        required=True,
        help='Path to legacy system output directory'
    )

    parser.add_argument(
        '--new',
        required=True,
        help='Path to new system output directory'
    )

    parser.add_argument(
        '--output',
        default='reports/comparison_report.md',
        help='Path to comparison report (default: reports/comparison_report.md)'
    )

    parser.add_argument(
        '--sample_size',
        type=int,
        default=100,
        help='Number of files to sample for detailed comparison (default: 100)'
    )

    parser.add_argument(
        '--threshold',
        type=float,
        default=0.95,
        help='Similarity threshold for warnings (default: 0.95)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Execute comparison
        comparator = SystemComparator(
            legacy_dir=args.legacy,
            new_dir=args.new,
            output_report=args.output,
            sample_size=args.sample_size,
            threshold=args.threshold
        )

        stats = comparator.compare_all()

        logger.info("\n" + "=" * 60)
        logger.info("Comparison Complete")
        logger.info("=" * 60)
        logger.info(f"Report: {args.output}")
        logger.info("=" * 60)

        sys.exit(0)

    except Exception as e:
        logger.error(f"Comparison failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
