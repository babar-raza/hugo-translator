#!/usr/bin/env python
"""Final validation test for HP-02 inline parsing."""
import sys
import os

# Setup paths
base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, 'src')
user_packages = r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages'

sys.path.insert(0, src_dir)
sys.path.insert(0, user_packages)

# Now import
from translation_engine.parser.hugo_parser import HugoParser
from translation_engine.parser.ast_nodes import NodeType

def find_nodes(nodes, node_type):
    """Recursively find all nodes of a given type."""
    found = []
    for n in nodes:
        if n.type == node_type:
            found.append(n)
        if n.children:
            found.extend(find_nodes(n.children, node_type))
    return found

print("=" * 70)
print("HP-02 INLINE PARSING VALIDATION TESTS")
print("=" * 70)
print()

parser = HugoParser()

# Test 1: Links
print("[Test 1] Link parsing")
doc = parser.parse_string("---\ntitle: t\n---\n[Click here](https://example.com)")
para = doc.ast[0]
links = [n for n in para.children if n.type == NodeType.LINK]
assert len(links) == 1, f"Expected 1 link, got {len(links)}"
assert links[0].attrs["url"] == "https://example.com"
print("  ✓ PASSED: Link node created with correct URL")

# Test 2: Bold
print("[Test 2] Bold parsing")
doc = parser.parse_string("---\ntitle: t\n---\nSome **bold** text")
para = doc.ast[0]
strongs = [n for n in para.children if n.type == NodeType.STRONG]
assert len(strongs) == 1
assert any(c.type == NodeType.TEXT for c in strongs[0].children)
print("  ✓ PASSED: STRONG node with TEXT child created")

# Test 3: Italic
print("[Test 3] Italic parsing")
doc = parser.parse_string("---\ntitle: t\n---\nSome *italic* text")
para = doc.ast[0]
ems = [n for n in para.children if n.type == NodeType.EMPHASIS]
assert len(ems) == 1
print("  ✓ PASSED: EMPHASIS node created")

# Test 4: Image
print("[Test 4] Image parsing")
doc = parser.parse_string("---\ntitle: t\n---\n![Alt text](image.png)")
para = doc.ast[0]
images = [n for n in para.children if n.type == NodeType.IMAGE]
assert len(images) == 1
assert images[0].attrs["src"] == "image.png"
assert images[0].attrs["alt"] == "Alt text"
print("  ✓ PASSED: IMAGE node with src and alt created")

# Test 5: Nested bold in link
print("[Test 5] Nested bold in link")
doc = parser.parse_string("---\ntitle: t\n---\n[**Bold link**](url)")
para = doc.ast[0]
links = [n for n in para.children if n.type == NodeType.LINK]
strongs = [c for c in links[0].children if c.type == NodeType.STRONG]
assert len(strongs) == 1
print("  ✓ PASSED: Nested STRONG inside LINK")

# Test 6: Nested link in bold
print("[Test 6] Nested link in bold")
doc = parser.parse_string("---\ntitle: t\n---\n**[link](url)**")
para = doc.ast[0]
strongs = [n for n in para.children if n.type == NodeType.STRONG]
links = [c for c in strongs[0].children if c.type == NodeType.LINK]
assert len(links) == 1
print("  ✓ PASSED: Nested LINK inside STRONG")

# Test 7: Link with title
print("[Test 7] Link with title attribute")
doc = parser.parse_string('---\ntitle: t\n---\n[Click](url "My Title")')
para = doc.ast[0]
links = [n for n in para.children if n.type == NodeType.LINK]
assert links[0].attrs.get("title") == "My Title"
print("  ✓ PASSED: Link title attribute preserved")

# Test 8: Complex example from HP-02 spec (CLI validation)
print("[Test 8] Complex example from HP-02 spec")
doc = parser.parse_string('''---
title: Test
---

Visit [Aspose](https://aspose.com) for **powerful** and *flexible* tools.
''')
para = doc.ast[0]
links = find_nodes(para.children, NodeType.LINK)
strongs = find_nodes(para.children, NodeType.STRONG)
ems = find_nodes(para.children, NodeType.EMPHASIS)

assert len(links) == 1, f'Expected 1 LINK, got {len(links)}'
assert links[0].attrs.get('url') == 'https://aspose.com'
assert len(strongs) == 1, f'Expected 1 STRONG, got {len(strongs)}'
assert len(ems) == 1, f'Expected 1 EMPHASIS, got {len(ems)}'
print("  ✓ PASSED: All inline elements in complex example")

# Test 9: Backward compatibility - plain text
print("[Test 9] Backward compatibility - plain text")
doc = parser.parse_string("---\ntitle: t\n---\nPlain text here")
para = doc.ast[0]
texts = [n for n in para.children if n.type == NodeType.TEXT]
assert len(texts) >= 1
print("  ✓ PASSED: Plain text still works")

print()
print("=" * 70)
print("✓✓✓ ALL 9 TESTS PASSED - HP-02 IMPLEMENTATION VERIFIED ✓✓✓")
print("=" * 70)
