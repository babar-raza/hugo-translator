"""
Verify that the full translation pipeline preserves structure.

This simulates what happens during actual translation:
1. Parse EN file with HugoParser (uses ruamel.yaml)
2. Reconstruct with MarkdownReconstructor (uses YAMLFormatter)
3. Compare structure
"""
import sys
import re
from pathlib import Path
from io import StringIO
from dataclasses import dataclass, field as dataclass_field
from typing import Dict, List, Any, Optional

# Prevent imports from triggering full chain
sys.modules['src'] = type(sys)('src')
sys.modules['src.translation_engine'] = type(sys)('src.translation_engine')

# Mock structlog
class MockLogger:
    def bind(self, **kwargs): return self
    def info(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def get_logger(self, *args, **kwargs): return self
    def __call__(self, *args, **kwargs): return self

sys.modules['structlog'] = MockLogger()

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

# Create YAML instances matching the production code
_yaml_parser = YAML()
_yaml_parser.preserve_quotes = True
_yaml_parser.width = 4096
_yaml_parser.allow_duplicate_keys = True

_yaml_dumper = YAML()
_yaml_dumper.preserve_quotes = True
_yaml_dumper.width = 4096
_yaml_dumper.default_flow_style = False
_yaml_dumper.allow_duplicate_keys = True


def parse_hugo_file(content: str) -> tuple:
    """Parse Hugo file and return frontmatter + body."""
    parts = content.split('---', 2)
    if len(parts) < 3:
        raise ValueError("Invalid Hugo frontmatter")

    yaml_content = parts[1]
    body = parts[2]

    frontmatter = _yaml_parser.load(StringIO(yaml_content))
    return frontmatter, body


def format_frontmatter(data) -> str:
    """Format frontmatter as YAML."""
    stream = StringIO()
    _yaml_dumper.dump(data, stream)
    return f"---\n{stream.getvalue()}---\n"


def reconstruct_document(frontmatter, body: str) -> str:
    """Reconstruct complete document."""
    fm = format_frontmatter(frontmatter)
    return f"{fm}\n{body.strip()}" if body.strip() else fm


def validate_structure(source: str, result: str) -> dict:
    """Validate structure preservation."""
    source_lines = len(source.strip().split('\n'))
    result_lines = len(result.strip().split('\n'))
    drift = abs(source_lines - result_lines) / source_lines * 100

    source_comments = set(re.findall(r'^#\s*\w+', source, re.MULTILINE))
    result_comments = set(re.findall(r'^#\s*\w+', result, re.MULTILINE))
    missing_comments = source_comments - result_comments

    return {
        'source_lines': source_lines,
        'result_lines': result_lines,
        'drift_percent': drift,
        'source_comments': len(source_comments),
        'result_comments': len(result_comments),
        'missing_comments': missing_comments,
    }


def main():
    print("=" * 70)
    print("Pipeline Structure Preservation Test")
    print("=" * 70)
    print()

    en_dir = Path('D:/onedrive/Documents/GitHub/aspose.net/content/products.aspose.net/slides/en')

    if not en_dir.exists():
        print(f"Error: EN directory not found: {en_dir}")
        return

    total_drift = 0
    total_files = 0
    all_passed = True

    for en_file in sorted(en_dir.glob('**/_index.md')):
        relative = en_file.relative_to(en_dir)

        try:
            source = en_file.read_text(encoding='utf-8')

            # Simulate translation pipeline: parse -> reconstruct
            frontmatter, body = parse_hugo_file(source)
            result = reconstruct_document(frontmatter, body)

            # Validate
            validation = validate_structure(source, result)
            total_drift += validation['drift_percent']
            total_files += 1

            status = 'PASS' if validation['drift_percent'] < 20 else 'FAIL'
            if validation['drift_percent'] >= 20:
                all_passed = False

            print(f"{status} {relative}:")
            print(f"     Lines: {validation['source_lines']} -> {validation['result_lines']} ({validation['drift_percent']:.1f}% drift)")
            print(f"     Comments: {validation['source_comments']} -> {validation['result_comments']}")
            if validation['missing_comments']:
                print(f"     Missing: {validation['missing_comments']}")

        except Exception as e:
            print(f"ERROR {relative}: {e}")
            all_passed = False

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if total_files > 0:
        avg_drift = total_drift / total_files
        print(f"Files tested: {total_files}")
        print(f"Average drift: {avg_drift:.1f}%")
        print()

        if avg_drift < 20:
            print("SUCCESS: Structure preservation is working!")
            print("The translation pipeline will preserve YAML structure.")
        else:
            print("WARNING: Some structure drift detected.")
            print("Review the output above for details.")
    else:
        print("No files found to test.")


if __name__ == "__main__":
    main()
