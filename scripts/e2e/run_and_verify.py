"""
Run translation and verify structure drift.
"""

import os
import sys

# Set up paths
os.chdir(r"C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator")
sys.path.insert(0, "src")

from io import StringIO
from pathlib import Path

print("=" * 70)
print("TRANSLATION AND STRUCTURE VERIFICATION")
print("=" * 70)

# Step 1: Test the CommentedMap fix
print("\n### Step 1: Testing CommentedMap preservation ###\n")

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

yaml = YAML()
yaml.preserve_quotes = True

test_yaml = """# Static
layout: "plugin"
# Header section
title: Test Title
body:
  enable: true
  block:
    - title_left: Block Title
      content_left: |
        This is a literal block
        with multiple lines
"""

# Parse and round-trip copy
original = yaml.load(StringIO(test_yaml))
print(f"Original type: {type(original).__name__}")

# Simulate the fix - round-trip copy
stream = StringIO()
yaml.dump(original, stream)
stream.seek(0)
copied = yaml.load(stream)

# Verify
output = StringIO()
yaml.dump(copied, output)
result = output.getvalue()

tests_passed = 0
tests_total = 3

if "# Static" in result:
    print("[PASS] Comment '# Static' preserved")
    tests_passed += 1
else:
    print("[FAIL] Comment '# Static' lost")

if "# Header section" in result:
    print("[PASS] Comment '# Header section' preserved")
    tests_passed += 1
else:
    print("[FAIL] Comment '# Header section' lost")

if "content_left: |" in result or "content_left: |-" in result:
    print("[PASS] Literal block style preserved")
    tests_passed += 1
else:
    print("[FAIL] Literal block style lost")
    print(f"Got: {result}")

print(f"\nRound-trip test: {tests_passed}/{tests_total} passed")

# Step 2: Test the MarkdownReconstructor fix
print("\n### Step 2: Testing MarkdownReconstructor ###\n")

try:
    import yaml as pyyaml

    from translation_engine.parser.hugo_parser import HugoParser
    from translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
    from utils.models import SiteProfile

    # Load site profile
    with open("config/site_profiles/products.aspose.net.yaml", encoding="utf-8") as f:
        profile_data = pyyaml.safe_load(f)

    site_profile = SiteProfile.from_config(profile_data)
    reconstructor = MarkdownReconstructor(site_profile)

    # Test _copy_commented_map
    copied = reconstructor._copy_commented_map(original)

    if isinstance(copied, CommentedMap):
        print("[PASS] _copy_commented_map returns CommentedMap")
    else:
        print("[FAIL] _copy_commented_map returns plain dict")

    # Verify comments preserved
    output = StringIO()
    yaml.dump(copied, output)
    result = output.getvalue()

    if "# Static" in result:
        print("[PASS] Comments preserved through _copy_commented_map")
    else:
        print("[FAIL] Comments lost through _copy_commented_map")

except Exception as e:
    print(f"[ERROR] MarkdownReconstructor test failed: {e}")
    import traceback

    traceback.print_exc()

# Step 3: Parse a real file and test reconstruction
print("\n### Step 3: Testing real file parsing ###\n")

try:
    parser = HugoParser(site_profile)

    en_file = Path(
        r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md"
    )

    if en_file.exists():
        with open(en_file, encoding="utf-8") as f:
            content = f.read()

        doc = parser.parse(content)

        # Check if frontmatter is CommentedMap
        if isinstance(doc.frontmatter, CommentedMap):
            print("[PASS] Parser returns CommentedMap frontmatter")
        else:
            print(f"[FAIL] Parser returns {type(doc.frontmatter).__name__}")

        # Check if comments are in the CommentedMap
        output = StringIO()
        yaml.dump(doc.frontmatter, output)
        fm_yaml = output.getvalue()

        comment_count = fm_yaml.count("#")
        print(f"Comments in parsed frontmatter: {comment_count}")

        if comment_count >= 5:
            print("[PASS] Comments preserved in parsed frontmatter")
        else:
            print("[WARN] Comments may not be fully preserved")

        # Test reconstruction
        print("\n### Step 4: Testing full reconstruction ###\n")

        # Create empty translations (just test structure preservation)
        translations = {}

        reconstructed_fm = reconstructor.reconstruct_frontmatter(
            doc.frontmatter, translations, "bg"
        )

        if isinstance(reconstructed_fm, CommentedMap):
            print("[PASS] Reconstructed frontmatter is CommentedMap")
        else:
            print(f"[FAIL] Reconstructed frontmatter is {type(reconstructed_fm).__name__}")

        # Dump and check
        output = StringIO()
        yaml.dump(reconstructed_fm, output)
        recon_yaml = output.getvalue()

        recon_comments = recon_yaml.count("#")
        print(f"Comments in reconstructed frontmatter: {recon_comments}")

        if "# Static" in recon_yaml:
            print("[PASS] '# Static' comment preserved after reconstruction")
        else:
            print("[FAIL] '# Static' comment lost after reconstruction")

        if "content: |" in recon_yaml or "content: |-" in recon_yaml:
            print("[PASS] Literal block preserved after reconstruction")
        else:
            print("[WARN] Literal block may have changed")

    else:
        print(f"[SKIP] EN file not found: {en_file}")

except Exception as e:
    print(f"[ERROR] Real file test failed: {e}")
    import traceback

    traceback.print_exc()

# Step 5: Compare EN vs BG structure
print("\n### Step 5: Current Structure Drift ###\n")

en_file = Path(
    r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md"
)
bg_file = Path(
    r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\bg\presentation-converter\_index.md"
)


def analyze_structure(filepath):
    if not filepath.exists():
        return None
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    return {
        "lines": len(lines),
        "comments": len([l for l in lines if l.strip().startswith("#")]),
        "literal_blocks": content.count(": |"),
        "blank_lines": len([l for l in lines if l.strip() == ""]),
    }


en_stats = analyze_structure(en_file)
bg_stats = analyze_structure(bg_file)

if en_stats and bg_stats:
    print(
        f"EN: {en_stats['lines']} lines, {en_stats['comments']} comments, {en_stats['literal_blocks']} literal blocks"
    )
    print(
        f"BG: {bg_stats['lines']} lines, {bg_stats['comments']} comments, {bg_stats['literal_blocks']} literal blocks"
    )

    line_drift = abs(en_stats["lines"] - bg_stats["lines"]) / en_stats["lines"] * 100
    comment_retention = (
        (bg_stats["comments"] / en_stats["comments"] * 100) if en_stats["comments"] > 0 else 100
    )
    literal_retention = (
        (bg_stats["literal_blocks"] / en_stats["literal_blocks"] * 100)
        if en_stats["literal_blocks"] > 0
        else 100
    )

    print(f"\nLine drift: {line_drift:.1f}%")
    print(f"Comment retention: {comment_retention:.1f}%")
    print(f"Literal block retention: {literal_retention:.1f}%")

print("\n" + "=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
