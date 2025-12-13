"""Direct test of reconstruction with structure preservation."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from io import StringIO
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Read the EN source file
EN_FILE = r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-converter\_index.md"

def parse_frontmatter(content):
    """Parse YAML frontmatter from Hugo content."""
    yaml = YAML()
    yaml.preserve_quotes = True

    # Extract frontmatter between ---
    lines = content.split('\n')
    if lines[0].strip() == '---':
        end_idx = None
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == '---':
                end_idx = i
                break
        if end_idx:
            fm_str = '\n'.join(lines[1:end_idx])
            return yaml.load(StringIO(fm_str))
    return None

def copy_commented_map_yaml_roundtrip(original, yaml_instance):
    """Copy CommentedMap using YAML round-trip (the fix)."""
    if isinstance(original, CommentedMap):
        stream = StringIO()
        yaml_instance.dump(original, stream)
        stream.seek(0)
        return yaml_instance.load(stream)
    return original

def format_frontmatter(data):
    """Format frontmatter back to YAML."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.width = 4096
    stream = StringIO()
    yaml.dump(data, stream)
    return '---\n' + stream.getvalue() + '---'

def main():
    print("=" * 60)
    print("DIRECT RECONSTRUCTION TEST")
    print("=" * 60)

    # Read EN file
    with open(EN_FILE, 'r', encoding='utf-8') as f:
        en_content = f.read()

    yaml = YAML()
    yaml.preserve_quotes = True

    # Parse frontmatter
    frontmatter = parse_frontmatter(en_content)

    if not isinstance(frontmatter, CommentedMap):
        print("[FAIL] Frontmatter is not CommentedMap")
        return

    print("[PASS] EN frontmatter is CommentedMap")

    # Simulate reconstruction using the fix
    copied = copy_commented_map_yaml_roundtrip(frontmatter, yaml)

    if not isinstance(copied, CommentedMap):
        print("[FAIL] Copied frontmatter is not CommentedMap")
        return

    print("[PASS] Copied frontmatter is CommentedMap")

    # Format back to YAML
    output = format_frontmatter(copied)

    # Count structures
    en_lines = en_content.split('\n')
    en_comments = len([l for l in en_lines if l.strip().startswith('#') and not ':' in l.split('#')[0]])
    en_literal = en_content.count(': |')

    out_lines = output.split('\n')
    out_comments = len([l for l in out_lines if l.strip().startswith('#') and not ':' in l.split('#')[0]])
    out_literal = output.count(': |') + output.count(': |-')

    print(f"\nEN source: {en_comments} comments, {en_literal} literal blocks")
    print(f"Reconstructed: {out_comments} comments, {out_literal} literal blocks")

    # Calculate retention
    if en_comments > 0:
        comment_retention = out_comments / en_comments * 100
        print(f"Comment retention: {comment_retention:.1f}%")
    else:
        comment_retention = 100

    if en_literal > 0:
        literal_retention = out_literal / en_literal * 100
        print(f"Literal block retention: {literal_retention:.1f}%")
    else:
        literal_retention = 100

    # Average drift
    comment_drift = 100 - comment_retention
    literal_drift = 100 - literal_retention
    avg_drift = (comment_drift + literal_drift) / 2

    print(f"\nAverage structure drift: {avg_drift:.1f}%")

    if avg_drift < 5:
        print("\n[PASS] Structure drift < 5% target")
    else:
        print("\n[FAIL] Structure drift >= 5% target")

    # Write output for inspection
    output_file = "reconstructed_test_output.md"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f"\nReconstructed output written to: {output_file}")

    # Show first 50 lines of output
    print("\n" + "=" * 60)
    print("FIRST 50 LINES OF OUTPUT:")
    print("=" * 60)
    for i, line in enumerate(out_lines[:50], 1):
        print(f"{i:3}: {line}")

if __name__ == "__main__":
    main()
