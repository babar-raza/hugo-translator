"""
End-to-end translation pipeline tests.

Verifies that source → parsed → extracted → reconstructed maintains
structural fidelity. Uses parse+extract+reconstruct directly (identity
translation) so no model loading is required.
"""

from pathlib import Path

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.utils.config_loader import ConfigService


def test_full_pipeline_preserves_structure():
    """Parse → extract → reconstruct preserves markdown structure."""

    source = """---
title: "Pipeline Test"
---

## Prerequisites

1. Install Visual Studio
2. Target .NET 6.0+
3. Install Aspose.Slides

## Links

- [Documentation](https://docs.example.com)
- [API Reference](https://api.example.com)

## Features

- **Performance**: Optimized for speed
- **Reliability**: Built on robust core
"""

    config_service = ConfigService(Path(__file__).parent.parent.parent / "config")
    site_profile = config_service.get_site_profile('kb.aspose.net')

    parser = HugoParser()
    parsed = parser.parse_string(source)

    extractor = TextUnitExtractor()
    plan = extractor.extract_from_ast(parsed.ast, parsed.frontmatter)

    # Identity translation: use source text unchanged
    translations = {
        u.node_addr: u.source_text
        for u in plan.units
        if u.node_addr and u.source_text
    }

    reconstructor = MarkdownReconstructor(site_profile)
    output = reconstructor.reconstruct_body(parsed.ast, translations, 'de')

    # Count structural elements in source body (exclude frontmatter)
    source_body = source.split('---', 2)[-1]
    source_ordered = source_body.count('\n1. ') + source_body.count('\n2. ') + source_body.count('\n3. ')
    source_bullets = source_body.count('\n- ')
    source_links = source_body.count('](')
    source_bold = source_body.count('**') // 2

    # Count in output
    out_ordered = output.count('\n1. ') + output.count('\n2. ') + output.count('\n3. ')
    out_bullets = output.count('\n- ')
    out_links = output.count('](')
    out_bold = output.count('**') // 2

    assert out_ordered == source_ordered, \
        f"Ordered lists: {source_ordered} → {out_ordered}"
    assert out_bullets == source_bullets, \
        f"Bullet lists: {source_bullets} → {out_bullets}"
    assert out_links == source_links, \
        f"Links: {source_links} → {out_links}"
    assert out_bold == source_bold, \
        f"Bold: {source_bold} → {out_bold}"
