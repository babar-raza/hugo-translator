"""Simple standalone test for structure preservation."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io import StringIO
from copy import deepcopy

# Only import what's needed
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Test data
SAMPLE_WITH_FULL_STRUCTURE = '''# Static
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
'''

def test_commented_map_preservation():
    """Test that ruamel.yaml preserves CommentedMap."""
    yaml = YAML()
    yaml.preserve_quotes = True

    # Parse YAML
    data = yaml.load(StringIO(SAMPLE_WITH_FULL_STRUCTURE))

    print("=" * 60)
    print("STRUCTURE PRESERVATION TESTS")
    print("=" * 60)

    # Test 1: Check it's a CommentedMap
    if isinstance(data, CommentedMap):
        print("[PASS] YAML parse returns CommentedMap")
    else:
        print(f"[FAIL] Got {type(data).__name__}, expected CommentedMap")

    # Test 2: Round-trip preserves comments
    stream = StringIO()
    yaml.dump(data, stream)
    output = stream.getvalue()

    comments_found = []
    for comment in ['# Static', '# Head', '# Overview', '# Body']:
        if comment in output:
            comments_found.append(comment)

    if len(comments_found) == 4:
        print(f"[PASS] YAML round-trip preserves all 4 comments")
    else:
        print(f"[FAIL] Only {len(comments_found)}/4 comments preserved: {comments_found}")

    # Test 3: deepcopy loses comments
    copied = deepcopy(data)
    if isinstance(copied, CommentedMap):
        stream2 = StringIO()
        yaml.dump(copied, stream2)
        output2 = stream2.getvalue()
        comments_after_deepcopy = sum(1 for c in ['# Static', '# Head', '# Overview', '# Body'] if c in output2)
        print(f"  deepcopy preserves {comments_after_deepcopy}/4 comments (expected to lose some)")
    else:
        print(f"  deepcopy converts to {type(copied).__name__}")

    # Test 4: YAML round-trip copy preserves comments
    stream3 = StringIO()
    yaml.dump(data, stream3)
    stream3.seek(0)
    copied_yaml = yaml.load(stream3)

    stream4 = StringIO()
    yaml.dump(copied_yaml, stream4)
    output4 = stream4.getvalue()

    yaml_copy_comments = sum(1 for c in ['# Static', '# Head', '# Overview', '# Body'] if c in output4)
    if yaml_copy_comments == 4:
        print(f"[PASS] YAML round-trip copy preserves all 4 comments")
    else:
        print(f"[FAIL] YAML round-trip copy preserves only {yaml_copy_comments}/4 comments")

    # Test 5: Literal blocks
    if 'content: |' in output or 'content: |-' in output:
        print("[PASS] Literal block style preserved")
    else:
        print("[FAIL] Literal block style not preserved")

    print("")
    return output

def compare_real_files():
    """Compare actual EN and BG files."""
    print("=" * 60)
    print("REAL FILE COMPARISON")
    print("=" * 60)

    en_file = r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md"
    bg_file = r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\bg\presentation-converter\_index.md"

    try:
        with open(en_file, 'r', encoding='utf-8') as f:
            en_content = f.read()
        with open(bg_file, 'r', encoding='utf-8') as f:
            bg_content = f.read()

        # Count structures in EN
        en_lines = en_content.split('\n')
        en_comments = len([l for l in en_lines if l.strip().startswith('#') and not l.strip().startswith('#-') and not ':' in l.split('#')[0]])
        en_literal = en_content.count(': |')

        # Count structures in BG
        bg_lines = bg_content.split('\n')
        bg_comments = len([l for l in bg_lines if l.strip().startswith('#') and not l.strip().startswith('#-') and not ':' in l.split('#')[0]])
        bg_literal = bg_content.count(': |') + bg_content.count(': |-')

        print(f"EN file: {len(en_lines)} lines, {en_comments} YAML comments, {en_literal} literal blocks")
        print(f"BG file: {len(bg_lines)} lines, {bg_comments} YAML comments, {bg_literal} literal blocks")

        # Structure drift
        if en_comments > 0:
            comment_retention = bg_comments / en_comments * 100
            comment_drift = 100 - comment_retention
            print(f"Comment retention: {comment_retention:.1f}% (drift: {comment_drift:.1f}%)")

        if en_literal > 0:
            literal_retention = bg_literal / en_literal * 100
            literal_drift = 100 - literal_retention
            print(f"Literal block retention: {literal_retention:.1f}% (drift: {literal_drift:.1f}%)")

        # Overall line drift
        line_diff = abs(len(en_lines) - len(bg_lines))
        line_drift = line_diff / len(en_lines) * 100
        print(f"Line count drift: {line_drift:.1f}% ({len(en_lines)} vs {len(bg_lines)})")

        # Check if under 5% target
        if en_comments > 0 and en_literal > 0:
            total_drift = (comment_drift + literal_drift) / 2
            if total_drift < 5:
                print(f"\n[PASS] Average structure drift {total_drift:.1f}% < 5% target")
            else:
                print(f"\n[FAIL] Average structure drift {total_drift:.1f}% >= 5% target")

    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_commented_map_preservation()
    print("")
    compare_real_files()
