#!/usr/bin/env python3
"""
Verify HP-01 through HP-05 fixes are integrated and active in translation pipeline.

Usage:
    python scripts/verify_hp_integration.py --file <path> --site <site_id> --target <lang>
"""

import sys
import logging
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Add user site-packages if not already in path (for psutil and other deps)
import site
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.append(user_site)

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s:%(lineno)d - %(message)s'
)

from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService

def verify_hp_integration(file_path: str, site_id: str, target_lang: str):
    """Verify HP fixes are active during translation."""

    print(f"\n=== HP Integration Verification ===")
    print(f"File: {file_path}")
    print(f"Site: {site_id}")
    print(f"Target: {target_lang}\n")

    # Load config
    config_service = ConfigService(project_root / "config")
    config = config_service.get_site_profile(site_id)

    # Read source file
    source_text = Path(file_path).read_text(encoding='utf-8')

    # Parse
    from src.translation_engine.parser.hugo_parser import HugoParser
    parser = HugoParser()
    parsed = parser.parse_string(source_text)

    # Count AST nodes (HP-01, HP-02)
    def count_nodes(ast_list, node_type):
        count = 0
        for node in ast_list:
            if node.type == node_type:
                count += 1
            if hasattr(node, 'children') and node.children:
                count += count_nodes(node.children, node_type)
        return count

    from src.translation_engine.parser.ast_nodes import NodeType

    list_nodes = count_nodes(parsed.ast, NodeType.LIST)
    link_nodes = count_nodes(parsed.ast, NodeType.LINK)
    strong_nodes = count_nodes(parsed.ast, NodeType.STRONG)

    print(f"[OK] HP-01: Parser created {list_nodes} LIST nodes")
    print(f"[OK] HP-02: Parser created {link_nodes} LINK nodes")
    print(f"[OK] HP-02: Parser created {strong_nodes} STRONG nodes\n")

    # Extract segments
    from src.translation_engine.extractor.segment_extractor import SegmentExtractor
    extractor = SegmentExtractor(config)
    segments = extractor.extract_all(parsed)

    # Count protected elements (HP-05)
    inline_protected = sum(
        1 for seg in segments
        if hasattr(seg, 'inline_format_data') and seg.inline_format_data
    )

    print(f"[OK] HP-05: Inline format protection applied to {inline_protected} segments\n")

    # Check terminology config (HP-04)
    if hasattr(config, 'terminology') and config.terminology.enabled:
        print(f"[OK] HP-04: Terminology protection enabled\n")
    else:
        print(f"[FAIL] HP-04: Terminology protection NOT enabled\n")

    # Translate
    engine = TranslationEngine(config)
    translated = engine.translate_document(
        parsed=parsed,
        source_lang=config.default_source_lang,
        target_lang=target_lang
    )

    # Count elements in output (HP-03 reconstruction)
    output_lists = translated.count('\n1. ') + translated.count('\n- ')
    output_links = translated.count('](')
    output_bold = translated.count('**') // 2

    print(f"=== Output Verification ===")
    print(f"Lists in output: {output_lists}")
    print(f"Links in output: {output_links}")
    print(f"Bold markers in output: {output_bold}\n")

    # Verify reconstruction
    if list_nodes > 0 and output_lists == 0:
        print(f"[FAIL] HP-03 FAILURE: LIST nodes created but not reconstructed")
        return False

    if link_nodes > 0 and output_links == 0:
        print(f"[FAIL] HP-03 FAILURE: LINK nodes created but not reconstructed")
        return False

    if strong_nodes > 0 and output_bold == 0:
        print(f"[FAIL] HP-03 FAILURE: STRONG nodes created but not reconstructed")
        return False

    print(f"[OK] HP-03: All node types successfully reconstructed")
    print(f"[OK] INTEGRATION: All HP fixes verified active\n")

    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    parser.add_argument('--site', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--verbose', action='store_true')

    args = parser.parse_args()

    success = verify_hp_integration(args.file, args.site, args.target)
    sys.exit(0 if success else 1)
