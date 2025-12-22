#!/usr/bin/env python
"""Simple test for HP-02 inline parsing."""

# Add src to path
import sys
import site
from pathlib import Path

# Add user site-packages to path
sys.path.insert(0, site.USER_SITE)
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# Import only what we need directly
import re
import uuid
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple, Union

import frontmatter as fm
from markdown_it import MarkdownIt
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Direct import to avoid init issues - use absolute path
import importlib.util
spec = importlib.util.spec_from_file_location("ast_nodes", "src/translation_engine/parser/ast_nodes.py")
ast_nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ast_nodes)

spec2 = importlib.util.spec_from_file_location("hugo_parser", "src/translation_engine/parser/hugo_parser.py")
hugo_parser = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(hugo_parser)

# Get the classes we need
ASTNode = ast_nodes.ASTNode
NodeType = ast_nodes.NodeType
HugoParser = hugo_parser.HugoParser

# Test basic functionality
print("Testing HP-02 Inline Parsing Implementation...")
print()

# Test 1: Link parsing
print("Test 1: Link parsing")
parser = HugoParser()
doc = parser.parse_string("---\ntitle: t\n---\n[Click here](https://example.com)")
para = doc.ast[0]
links = [n for n in para.children if n.type == NodeType.LINK]
assert len(links) == 1, f"Expected 1 link, got {len(links)}"
assert links[0].attrs["url"] == "https://example.com", f"URL mismatch: {links[0].attrs}"
print("  ✓ Link parsed correctly")

# Test 2: Bold parsing
print("Test 2: Bold parsing")
doc = parser.parse_string("---\ntitle: t\n---\nSome **bold** text")
para = doc.ast[0]
strongs = [n for n in para.children if n.type == NodeType.STRONG]
assert len(strongs) == 1, f"Expected 1 strong, got {len(strongs)}"
assert any(c.type == NodeType.TEXT for c in strongs[0].children), "Strong should have TEXT child"
print("  ✓ Bold parsed correctly")

# Test 3: Italic parsing
print("Test 3: Italic parsing")
doc = parser.parse_string("---\ntitle: t\n---\nSome *italic* text")
para = doc.ast[0]
ems = [n for n in para.children if n.type == NodeType.EMPHASIS]
assert len(ems) == 1, f"Expected 1 emphasis, got {len(ems)}"
print("  ✓ Italic parsed correctly")

# Test 4: Image parsing
print("Test 4: Image parsing")
doc = parser.parse_string("---\ntitle: t\n---\n![Alt text](image.png)")
para = doc.ast[0]
images = [n for n in para.children if n.type == NodeType.IMAGE]
assert len(images) == 1, f"Expected 1 image, got {len(images)}"
assert images[0].attrs["src"] == "image.png", f"Image src mismatch: {images[0].attrs}"
assert images[0].attrs["alt"] == "Alt text", f"Image alt mismatch: {images[0].attrs}"
print("  ✓ Image parsed correctly")

# Test 5: Nested bold in link
print("Test 5: Nested bold in link")
doc = parser.parse_string("---\ntitle: t\n---\n[**Bold link**](url)")
para = doc.ast[0]
links = [n for n in para.children if n.type == NodeType.LINK]
assert len(links) == 1, f"Expected 1 link, got {len(links)}"
strongs = [c for c in links[0].children if c.type == NodeType.STRONG]
assert len(strongs) == 1, f"Expected 1 strong in link, got {len(strongs)}"
print("  ✓ Nested bold in link parsed correctly")

# Test 6: Nested link in bold
print("Test 6: Nested link in bold")
doc = parser.parse_string("---\ntitle: t\n---\n**[link](url)**")
para = doc.ast[0]
strongs = [n for n in para.children if n.type == NodeType.STRONG]
assert len(strongs) == 1, f"Expected 1 strong, got {len(strongs)}"
links = [c for c in strongs[0].children if c.type == NodeType.LINK]
assert len(links) == 1, f"Expected 1 link in strong, got {len(links)}"
print("  ✓ Nested link in bold parsed correctly")

# Test 7: Complex example from HP-02 spec
print("Test 7: Complex example from HP-02 spec")
doc = parser.parse_string('''---
title: Test
---

Visit [Aspose](https://aspose.com) for **powerful** and *flexible* tools.
''')
para = doc.ast[0]

def find_nodes(nodes, node_type):
    found = []
    for n in nodes:
        if n.type == node_type:
            found.append(n)
        if n.children:
            found.extend(find_nodes(n.children, node_type))
    return found

links = find_nodes(para.children, NodeType.LINK)
strongs = find_nodes(para.children, NodeType.STRONG)
ems = find_nodes(para.children, NodeType.EMPHASIS)

assert len(links) == 1, f'Expected 1 LINK, got {len(links)}'
assert links[0].attrs.get('url') == 'https://aspose.com', f'URL not preserved, got {links[0].attrs}'
assert len(strongs) == 1, f'Expected 1 STRONG, got {len(strongs)}'
assert len(ems) == 1, f'Expected 1 EMPHASIS, got {len(ems)}'
print("  ✓ Complex example parsed correctly")

print()
print("=" * 60)
print("✓ ALL TESTS PASSED - HP-02 Implementation Complete!")
print("=" * 60)
