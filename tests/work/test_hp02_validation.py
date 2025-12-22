#!/usr/bin/env python
"""CLI validation for HP-02 inline parsing."""
import sys
sys.path.insert(0, 'src')
from translation_engine.parser.hugo_parser import HugoParser
from translation_engine.parser.ast_nodes import NodeType

parser = HugoParser()
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

print('✓ CLI validation passed')
print(f'  - Found {len(links)} LINK node(s)')
print(f'  - Found {len(strongs)} STRONG node(s)')
print(f'  - Found {len(ems)} EMPHASIS node(s)')
