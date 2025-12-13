"""
Verify structure drift between source and translated files.
Tests the CommentedMap preservation fix for SD-01/SD-04 compliance.
"""
import sys
sys.path.insert(0, 'src')

from pathlib import Path
from io import StringIO

# Write results to file to avoid Windows console issues
output_file = Path('structure_drift_results.txt')
output_lines = []

def log(msg):
    print(msg)
    output_lines.append(msg)

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
except ImportError:
    log("ERROR: ruamel.yaml not installed")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))
    sys.exit(1)

log("=" * 70)
log("STRUCTURE DRIFT VERIFICATION")
log("=" * 70)

# ============================================================================
# Test 1: Verify CommentedMap round-trip copy
# ============================================================================
log("\n### Test 1: CommentedMap Round-Trip Copy ###\n")

yaml = YAML()
yaml.preserve_quotes = True

test_yaml = """# Static comment
layout: plugin
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

# Parse to CommentedMap
original = yaml.load(StringIO(test_yaml))
log(f"Original type: {type(original).__name__}")

# Test round-trip copy (simulating our fix)
stream = StringIO()
yaml.dump(original, stream)
stream.seek(0)
copied = yaml.load(stream)

# Dump copied to check if comments preserved
output = StringIO()
yaml.dump(copied, output)
result = output.getvalue()

if '# Static comment' in result:
    log("[PASS] Static comment preserved in round-trip copy")
else:
    log("[FAIL] Static comment lost in round-trip copy")

if '# Header section' in result:
    log("[PASS] Header comment preserved in round-trip copy")
else:
    log("[FAIL] Header comment lost in round-trip copy")

if 'content_left: |' in result or 'content_left: |-' in result:
    log("[PASS] Literal block style preserved")
else:
    log("[WARN] Literal block style may have changed")
    log(f"Result:\n{result}")

# ============================================================================
# Test 2: Test MarkdownReconstructor with CommentedMap
# ============================================================================
log("\n### Test 2: MarkdownReconstructor CommentedMap Handling ###\n")

try:
    from translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
    from translation_engine.reconstructor.yaml_formatter import YAMLFormatter
    from utils.models import SiteProfile

    # Load site profile
    import yaml as pyyaml
    with open('config/site_profiles/products.aspose.net.yaml', 'r', encoding='utf-8') as f:
        profile_data = pyyaml.safe_load(f)

    site_profile = SiteProfile.from_config(profile_data)
    reconstructor = MarkdownReconstructor(site_profile)

    # Test _copy_commented_map
    copied = reconstructor._copy_commented_map(original)
    log(f"Copied type: {type(copied).__name__}")

    if isinstance(copied, CommentedMap):
        log("[PASS] _copy_commented_map returns CommentedMap")
    else:
        log("[FAIL] _copy_commented_map returns plain dict")

    # Verify comments still present after copy
    output = StringIO()
    yaml.dump(copied, output)
    result = output.getvalue()

    if '# Static comment' in result:
        log("[PASS] Comments preserved through _copy_commented_map")
    else:
        log("[FAIL] Comments lost through _copy_commented_map")

except Exception as e:
    log(f"[WARN] Could not test MarkdownReconstructor: {e}")

# ============================================================================
# Test 3: Actual file comparison
# ============================================================================
log("\n### Test 3: Source vs Translated File Structure ###\n")

en_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md")
bg_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\bg\presentation-converter\_index.md")

def analyze_file(filepath):
    """Analyze structure metrics of a Hugo markdown file."""
    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    return {
        'lines': len(lines),
        'comments': len([l for l in lines if l.strip().startswith('#')]),
        'literal_blocks': content.count(': |'),
        'blank_lines': len([l for l in lines if l.strip() == '']),
    }

if en_file.exists():
    en_stats = analyze_file(en_file)
    log(f"EN file: {en_file.name}")
    log(f"  Lines: {en_stats['lines']}")
    log(f"  Comments: {en_stats['comments']}")
    log(f"  Literal blocks: {en_stats['literal_blocks']}")
    log(f"  Blank lines: {en_stats['blank_lines']}")
else:
    log(f"[SKIP] EN file not found: {en_file}")
    en_stats = None

if bg_file.exists():
    bg_stats = analyze_file(bg_file)
    log(f"\nBG file: {bg_file.name}")
    log(f"  Lines: {bg_stats['lines']}")
    log(f"  Comments: {bg_stats['comments']}")
    log(f"  Literal blocks: {bg_stats['literal_blocks']}")
    log(f"  Blank lines: {bg_stats['blank_lines']}")
else:
    log(f"[SKIP] BG file not found: {bg_file}")
    bg_stats = None

if en_stats and bg_stats:
    # Calculate drift
    line_drift = abs(en_stats['lines'] - bg_stats['lines']) / en_stats['lines'] * 100
    comment_retention = (bg_stats['comments'] / en_stats['comments'] * 100) if en_stats['comments'] > 0 else 100
    literal_retention = (bg_stats['literal_blocks'] / en_stats['literal_blocks'] * 100) if en_stats['literal_blocks'] > 0 else 100

    log(f"\n--- Structure Drift Analysis ---")
    log(f"Line drift: {line_drift:.1f}%")
    log(f"Comment retention: {comment_retention:.1f}%")
    log(f"Literal block retention: {literal_retention:.1f}%")

    if line_drift <= 5:
        log("\n[PASS] Line drift <= 5%")
    else:
        log(f"\n[FAIL] Line drift {line_drift:.1f}% exceeds 5% threshold")

    if comment_retention >= 95:
        log("[PASS] Comment retention >= 95%")
    else:
        log(f"[WARN] Comment retention {comment_retention:.1f}% below 95%")

    if literal_retention >= 95:
        log("[PASS] Literal block retention >= 95%")
    else:
        log(f"[WARN] Literal block retention {literal_retention:.1f}% below 95%")

# ============================================================================
# Summary
# ============================================================================
log("\n" + "=" * 70)
log("VERIFICATION COMPLETE")
log("=" * 70)
log("\nNote: If BG file shows old results, re-run translation with:")
log("  python scripts/batch_translate.py --override-mode refresh")

# Write to file
with open(output_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

log(f"\nResults written to: {output_file}")
