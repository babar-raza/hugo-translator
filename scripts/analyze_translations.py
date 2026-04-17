#!/usr/bin/env python3
"""
Translation Quality Analyzer
Compares EN source files against DE/FR translations to find structural drift and gaps.
"""

import re
from collections import defaultdict
from pathlib import Path

import frontmatter

# Base paths
BASE_PATH = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides")
EN_PATH = BASE_PATH / "en"
DE_PATH = BASE_PATH / "de"
FR_PATH = BASE_PATH / "fr"

# Protected terms that should NOT be translated
PROTECTED_TERMS = [
    "Aspose.Slides", "Aspose.Words", "Aspose.Cells", "Aspose.PDF",
    "NuGet", "PowerPoint", "Visual Studio", "PdfOptions",
    "PPTX", "POTX", "ODP", "PDF/A",
    ".NET Framework", ".NET Core", ".NET Standard",
    "SaveFormat", "Presentation class"
]

# Regex patterns for structural elements
PATTERNS = {
    'ordered_list': re.compile(r'^\s*\d+\.\s+', re.MULTILINE),
    'bullet_list': re.compile(r'^\s*[-*]\s+', re.MULTILINE),
    'link': re.compile(r'\[([^\]]+)\]\(([^)]+)\)'),
    'bold': re.compile(r'\*\*([^*]+)\*\*'),
    'italic': re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)'),
    'code_block': re.compile(r'```[\s\S]*?```'),
    'inline_code': re.compile(r'`[^`]+`'),
    'shortcode': re.compile(r'\{\{[<%].*?[%>]\}\}'),
    'heading': re.compile(r'^#{1,6}\s+.+$', re.MULTILINE),
}


class TranslationAnalyzer:
    def __init__(self):
        self.results = {
            'file_count': {'en': 0, 'de': 0, 'fr': 0},
            'missing_files': {'de': [], 'fr': []},
            'structural_drift': [],
            'terminology_violations': [],
            'untranslated_content': [],
            'link_drift': [],
            'list_drift': [],
            'summary': {}
        }

    def count_pattern(self, content, pattern_name):
        """Count occurrences of a pattern in content."""
        pattern = PATTERNS[pattern_name]
        return len(pattern.findall(content))

    def extract_links(self, content):
        """Extract all links with their text and URLs."""
        return PATTERNS['link'].findall(content)

    def extract_bold(self, content):
        """Extract all bold text."""
        return PATTERNS['bold'].findall(content)

    def check_terminology(self, content, lang, filename):
        """Check if protected terms were incorrectly translated."""
        violations = []
        for term in PROTECTED_TERMS:
            # Check if term appears in EN but not in translation
            # We can't check absence directly, but we can flag suspicious patterns
            if term.lower() in content.lower():
                # Term is present (good)
                pass
        return violations

    def analyze_file(self, en_file):
        """Analyze a single file across all languages."""
        rel_path = en_file.relative_to(EN_PATH)
        de_file = DE_PATH / rel_path
        fr_file = FR_PATH / rel_path

        result = {
            'file': str(rel_path),
            'en': {'exists': True},
            'de': {'exists': de_file.exists()},
            'fr': {'exists': fr_file.exists()},
            'issues': []
        }

        # Read EN content
        try:
            en_post = frontmatter.load(en_file)
            en_content = en_post.content
            en_meta = en_post.metadata
        except Exception as e:
            result['issues'].append(f"EN read error: {e}")
            return result

        # Count EN structural elements
        en_stats = {
            'ordered_lists': self.count_pattern(en_content, 'ordered_list'),
            'bullet_lists': self.count_pattern(en_content, 'bullet_list'),
            'links': len(self.extract_links(en_content)),
            'bold': len(self.extract_bold(en_content)),
            'code_blocks': self.count_pattern(en_content, 'code_block'),
            'inline_code': self.count_pattern(en_content, 'inline_code'),
            'shortcodes': self.count_pattern(en_content, 'shortcode'),
            'headings': self.count_pattern(en_content, 'heading'),
        }
        result['en']['stats'] = en_stats

        # Analyze DE translation
        if de_file.exists():
            try:
                de_post = frontmatter.load(de_file)
                de_content = de_post.content
                de_meta = de_post.metadata

                de_stats = {
                    'ordered_lists': self.count_pattern(de_content, 'ordered_list'),
                    'bullet_lists': self.count_pattern(de_content, 'bullet_list'),
                    'links': len(self.extract_links(de_content)),
                    'bold': len(self.extract_bold(de_content)),
                    'code_blocks': self.count_pattern(de_content, 'code_block'),
                    'inline_code': self.count_pattern(de_content, 'inline_code'),
                    'shortcodes': self.count_pattern(de_content, 'shortcode'),
                    'headings': self.count_pattern(de_content, 'heading'),
                }
                result['de']['stats'] = de_stats

                # Check for structural drift
                for key in en_stats:
                    if en_stats[key] != de_stats[key]:
                        result['issues'].append(
                            f"DE {key} drift: EN={en_stats[key]}, DE={de_stats[key]}"
                        )

                # Check links preserved
                en_links = self.extract_links(en_content)
                de_links = self.extract_links(de_content)
                en_urls = set(url for _, url in en_links)
                de_urls = set(url for _, url in de_links)
                if en_urls != de_urls:
                    missing = en_urls - de_urls
                    if missing:
                        result['issues'].append(f"DE missing URLs: {missing}")

                # Check terminology
                for term in PROTECTED_TERMS:
                    en_count = en_content.count(term)
                    de_count = de_content.count(term)
                    if en_count > 0 and de_count < en_count:
                        result['issues'].append(
                            f"DE terminology: '{term}' EN={en_count}, DE={de_count}"
                        )

            except Exception as e:
                result['issues'].append(f"DE read error: {e}")
        else:
            self.results['missing_files']['de'].append(str(rel_path))

        # Analyze FR translation
        if fr_file.exists():
            try:
                fr_post = frontmatter.load(fr_file)
                fr_content = fr_post.content
                fr_meta = fr_post.metadata

                fr_stats = {
                    'ordered_lists': self.count_pattern(fr_content, 'ordered_list'),
                    'bullet_lists': self.count_pattern(fr_content, 'bullet_list'),
                    'links': len(self.extract_links(fr_content)),
                    'bold': len(self.extract_bold(fr_content)),
                    'code_blocks': self.count_pattern(fr_content, 'code_block'),
                    'inline_code': self.count_pattern(fr_content, 'inline_code'),
                    'shortcodes': self.count_pattern(fr_content, 'shortcode'),
                    'headings': self.count_pattern(fr_content, 'heading'),
                }
                result['fr']['stats'] = fr_stats

                # Check for structural drift
                for key in en_stats:
                    if en_stats[key] != fr_stats[key]:
                        result['issues'].append(
                            f"FR {key} drift: EN={en_stats[key]}, FR={fr_stats[key]}"
                        )

                # Check links preserved
                fr_links = self.extract_links(fr_content)
                fr_urls = set(url for _, url in fr_links)
                if en_urls != fr_urls:
                    missing = en_urls - fr_urls
                    if missing:
                        result['issues'].append(f"FR missing URLs: {missing}")

                # Check terminology
                for term in PROTECTED_TERMS:
                    en_count = en_content.count(term)
                    fr_count = fr_content.count(term)
                    if en_count > 0 and fr_count < en_count:
                        result['issues'].append(
                            f"FR terminology: '{term}' EN={en_count}, FR={fr_count}"
                        )

            except Exception as e:
                result['issues'].append(f"FR read error: {e}")
        else:
            self.results['missing_files']['fr'].append(str(rel_path))

        return result

    def run_analysis(self):
        """Run full analysis on all files."""
        print("=" * 70)
        print("TRANSLATION QUALITY ANALYSIS")
        print("=" * 70)

        en_files = list(EN_PATH.rglob("*.md"))
        self.results['file_count']['en'] = len(en_files)
        self.results['file_count']['de'] = len(list(DE_PATH.rglob("*.md")))
        self.results['file_count']['fr'] = len(list(FR_PATH.rglob("*.md")))

        print(f"\nFile counts: EN={self.results['file_count']['en']}, "
              f"DE={self.results['file_count']['de']}, "
              f"FR={self.results['file_count']['fr']}")

        # Aggregate stats
        total_stats = {
            'en': defaultdict(int),
            'de': defaultdict(int),
            'fr': defaultdict(int),
        }

        files_with_issues = []
        issue_counts = defaultdict(int)

        for en_file in sorted(en_files):
            result = self.analyze_file(en_file)

            # Aggregate stats
            if 'stats' in result['en']:
                for key, val in result['en']['stats'].items():
                    total_stats['en'][key] += val
            if 'stats' in result.get('de', {}):
                for key, val in result['de']['stats'].items():
                    total_stats['de'][key] += val
            if 'stats' in result.get('fr', {}):
                for key, val in result['fr']['stats'].items():
                    total_stats['fr'][key] += val

            if result['issues']:
                files_with_issues.append(result)
                for issue in result['issues']:
                    # Categorize issue
                    if 'drift' in issue:
                        issue_type = issue.split()[1]  # e.g., "ordered_lists"
                        issue_counts[f"{issue.split()[0]}_{issue_type}_drift"] += 1
                    elif 'terminology' in issue:
                        issue_counts['terminology_violation'] += 1
                    elif 'missing URLs' in issue:
                        issue_counts['missing_urls'] += 1

        # Print aggregate stats
        print("\n" + "=" * 70)
        print("STRUCTURAL ELEMENT COUNTS")
        print("=" * 70)
        print(f"\n{'Element':<20} {'EN':<10} {'DE':<10} {'FR':<10} {'DE Diff':<10} {'FR Diff':<10}")
        print("-" * 70)
        for key in ['ordered_lists', 'bullet_lists', 'links', 'bold',
                    'code_blocks', 'inline_code', 'shortcodes', 'headings']:
            en_val = total_stats['en'][key]
            de_val = total_stats['de'][key]
            fr_val = total_stats['fr'][key]
            de_diff = de_val - en_val
            fr_diff = fr_val - en_val
            de_diff_str = f"+{de_diff}" if de_diff > 0 else str(de_diff)
            fr_diff_str = f"+{fr_diff}" if fr_diff > 0 else str(fr_diff)
            print(f"{key:<20} {en_val:<10} {de_val:<10} {fr_val:<10} {de_diff_str:<10} {fr_diff_str:<10}")

        # Print issue summary
        print("\n" + "=" * 70)
        print("ISSUE SUMMARY")
        print("=" * 70)
        print(f"\nFiles with issues: {len(files_with_issues)} / {len(en_files)}")
        print("\nIssue breakdown:")
        for issue_type, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"  - {issue_type}: {count}")

        # Print detailed issues (first 20)
        if files_with_issues:
            print("\n" + "=" * 70)
            print("DETAILED ISSUES (showing first 20 files)")
            print("=" * 70)
            for result in files_with_issues[:20]:
                print(f"\n📄 {result['file']}")
                for issue in result['issues']:
                    print(f"   ⚠️  {issue}")

        # Store for report
        self.results['total_stats'] = dict(total_stats)
        self.results['files_with_issues'] = files_with_issues
        self.results['issue_counts'] = dict(issue_counts)

        return self.results


def main():
    analyzer = TranslationAnalyzer()
    results = analyzer.run_analysis()

    # Summary
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)

    total_issues = sum(results['issue_counts'].values())
    files_with_issues = len(results['files_with_issues'])

    if total_issues == 0:
        print("\n✅ NO STRUCTURAL DRIFT DETECTED")
        print("All translations preserve source structure correctly.")
    else:
        print(f"\n⚠️  FOUND {total_issues} ISSUES in {files_with_issues} files")
        print("\nRecommended actions:")
        if results['issue_counts'].get('terminology_violation', 0) > 0:
            print("  1. Review terminology protection rules")
        if any('drift' in k for k in results['issue_counts']):
            print("  2. Check parser/reconstructor for structural elements")
        if results['issue_counts'].get('missing_urls', 0) > 0:
            print("  3. Verify link preservation in translation")


if __name__ == "__main__":
    main()
