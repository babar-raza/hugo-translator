#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Add user site-packages
import site
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.append(user_site)

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.parser.ast_nodes import NodeType

def count_nodes(ast_list, node_type):
    count = 0
    for node in ast_list:
        if node.type == node_type:
            count += 1
            print(f"  Found {node_type}: attrs={node.attrs if hasattr(node, 'attrs') else 'none'}")
        if hasattr(node, 'children') and node.children:
            count += count_nodes(node.children, node_type)
    return count

# Test link parsing
parser = HugoParser()
source = Path('tests/fixtures/hp_validation/en/02_links.md').read_text(encoding='utf-8')
doc = parser.parse_string(source)

print("=== Parsing Results ===")
link_count = count_nodes(doc.ast, NodeType.LINK)
print(f"\nTotal LINK nodes: {link_count}")

# Now test reconstruction
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.config_loader import ConfigService

config_service = ConfigService(project_root / 'config')
site_profile = config_service.get_site_profile('kb.aspose.net')

reconstructor = MarkdownReconstructor(site_profile)
reconstructed = reconstructor.reconstruct_body(doc.ast)

print("\n=== Reconstructed Output ===")
print(reconstructed)
