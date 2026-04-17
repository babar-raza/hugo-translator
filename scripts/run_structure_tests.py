"""Run structure preservation tests and write results to file."""
import os
import sys

# Set up paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Import our modules
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
from src.utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile

# Test data
SAMPLE_WITH_FULL_STRUCTURE = '''---
# Static
layout: "plugin"
cart_id: ""

# Head
head_title: "Test Title"
head_description: "Test Description"

# Overview
overview:
  enable: true
  title: "Overview Title"
  content: |
    This is a multi-line literal block.
    It should preserve newlines and formatting.

# Body
body:
  enable: true
  block:
    - title_left: "First Block"
      content_left: |
        First block content
        with multiple lines
    - title_left: "Second Block"
      content_left: |
        Second block content
---

Body content here.
'''

def create_test_profile():
    """Create test profile for reconstruction."""
    return SiteProfile(
        site_id="test-site",
        content_roots=["/content/test"],
        default_source_lang="en",
        target_langs=["bg"],
        frontmatter={
            "layout": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "cart_id": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "head_title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "head_description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "overview.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "overview.content": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "body.block.title_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "body.block.content_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code"],
            preserve_patterns=[],
            placeholder_syntax=[],
        ),
    )

def run_tests():
    results = []
    passed = 0
    failed = 0

    profile = create_test_profile()
    parser = HugoParser()
    reconstructor = MarkdownReconstructor(profile)

    # Test 1: Parser returns CommentedMap
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        if isinstance(doc.frontmatter, CommentedMap):
            results.append("✓ PASS: Parser returns CommentedMap")
            passed += 1
        else:
            results.append(f"✗ FAIL: Parser returns {type(doc.frontmatter).__name__}, expected CommentedMap")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: Parser test failed: {e}")
        failed += 1

    # Test 2: _copy_commented_map preserves type
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        copied = reconstructor._copy_commented_map(doc.frontmatter)
        if isinstance(copied, CommentedMap):
            results.append("✓ PASS: _copy_commented_map returns CommentedMap")
            passed += 1
        else:
            results.append(f"✗ FAIL: _copy_commented_map returns {type(copied).__name__}, expected CommentedMap")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: _copy_commented_map type test failed: {e}")
        failed += 1

    # Test 3: _copy_commented_map preserves comments
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        copied = reconstructor._copy_commented_map(doc.frontmatter)

        yaml = YAML()
        yaml.preserve_quotes = True
        stream = StringIO()
        yaml.dump(copied, stream)
        output = stream.getvalue()

        comments_found = []
        for comment in ['# Static', '# Head', '# Overview', '# Body']:
            if comment in output:
                comments_found.append(comment)

        if len(comments_found) == 4:
            results.append("✓ PASS: _copy_commented_map preserves all 4 comments")
            passed += 1
        else:
            results.append(f"✗ FAIL: Only {len(comments_found)}/4 comments preserved: {comments_found}")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: _copy_commented_map comment test failed: {e}")
        failed += 1

    # Test 4: reconstruct_frontmatter preserves CommentedMap
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_frontmatter(doc.frontmatter, {}, "bg")
        if isinstance(result, CommentedMap):
            results.append("✓ PASS: reconstruct_frontmatter returns CommentedMap")
            passed += 1
        else:
            results.append(f"✗ FAIL: reconstruct_frontmatter returns {type(result).__name__}")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: reconstruct_frontmatter type test failed: {e}")
        failed += 1

    # Test 5: Literal blocks in output
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_frontmatter(doc.frontmatter, {}, "bg")
        output = YAMLFormatter.format_frontmatter(result)

        if 'content: |' in output or 'content: |-' in output:
            results.append("✓ PASS: Literal block style preserved in output")
            passed += 1
        else:
            results.append("✗ FAIL: No literal block style found in output")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: Literal block test failed: {e}")
        failed += 1

    # Test 6: Full document reconstruction
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_document(doc, {}, "bg")

        has_comments = '# Static' in result and '# Head' in result
        has_literal = 'content: |' in result or 'content: |-' in result

        if has_comments and has_literal:
            results.append("✓ PASS: Full document preserves comments and literal blocks")
            passed += 1
        else:
            results.append(f"✗ FAIL: Full doc - comments: {has_comments}, literal: {has_literal}")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: Full document test failed: {e}")
        failed += 1

    # Test 7: Structure drift measurement
    try:
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_document(doc, {}, "bg")

        # Count in original
        original_lines = SAMPLE_WITH_FULL_STRUCTURE.split('\n')
        original_comments = len([l for l in original_lines if l.strip().startswith('#')])
        original_literal = SAMPLE_WITH_FULL_STRUCTURE.count(': |')

        # Count in result
        result_lines = result.split('\n')
        result_comments = len([l for l in result_lines if l.strip().startswith('#')])
        result_literal = result.count(': |') + result.count(': |-')

        comment_retention = result_comments / original_comments * 100 if original_comments > 0 else 100
        literal_retention = result_literal / original_literal * 100 if original_literal > 0 else 100

        results.append(f"  Comments: {result_comments}/{original_comments} ({comment_retention:.1f}% retention)")
        results.append(f"  Literal blocks: {result_literal}/{original_literal} ({literal_retention:.1f}% retention)")

        if comment_retention >= 80 and literal_retention >= 80:
            results.append("✓ PASS: Structure drift < 20%")
            passed += 1
        else:
            results.append("✗ FAIL: Structure drift > 20%")
            failed += 1
    except Exception as e:
        results.append(f"✗ ERROR: Structure drift test failed: {e}")
        failed += 1

    return results, passed, failed

def compare_real_files():
    """Compare actual EN and BG files for structure drift."""
    results = []

    en_file = r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md"
    bg_file = r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\bg\presentation-converter\_index.md"

    try:
        with open(en_file, encoding='utf-8') as f:
            en_content = f.read()
        with open(bg_file, encoding='utf-8') as f:
            bg_content = f.read()

        # Count structures in EN
        en_lines = en_content.split('\n')
        en_comments = len([l for l in en_lines if l.strip().startswith('#') and not l.strip().startswith('#-')])
        en_literal = en_content.count(': |')

        # Count structures in BG
        bg_lines = bg_content.split('\n')
        bg_comments = len([l for l in bg_lines if l.strip().startswith('#') and not l.strip().startswith('#-')])
        bg_literal = bg_content.count(': |') + bg_content.count(': |-')

        results.append("\n=== REAL FILE COMPARISON ===")
        results.append(f"EN file: {len(en_lines)} lines, {en_comments} comments, {en_literal} literal blocks")
        results.append(f"BG file: {len(bg_lines)} lines, {bg_comments} comments, {bg_literal} literal blocks")

        if en_comments > 0:
            comment_retention = bg_comments / en_comments * 100
            results.append(f"Comment retention: {comment_retention:.1f}%")

        if en_literal > 0:
            literal_retention = bg_literal / en_literal * 100
            results.append(f"Literal block retention: {literal_retention:.1f}%")

        # Calculate overall drift
        line_diff = abs(len(en_lines) - len(bg_lines))
        line_drift = line_diff / len(en_lines) * 100 if en_lines else 0
        results.append(f"Line count drift: {line_drift:.1f}%")

    except FileNotFoundError as e:
        results.append(f"Could not compare real files: {e}")
    except Exception as e:
        results.append(f"Error comparing files: {e}")

    return results

if __name__ == "__main__":
    output_file = "structure_test_results.txt"

    print("Running structure preservation tests...")

    test_results, passed, failed = run_tests()
    file_results = compare_real_files()

    all_results = [
        "=" * 60,
        "STRUCTURE PRESERVATION TEST RESULTS",
        "=" * 60,
        "",
    ] + test_results + [
        "",
        f"SUMMARY: {passed} passed, {failed} failed",
    ] + file_results

    # Write to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_results))

    # Also print
    print('\n'.join(all_results))
    print(f"\nResults written to {output_file}")
