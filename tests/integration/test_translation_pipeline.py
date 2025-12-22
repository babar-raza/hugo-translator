"""
End-to-end translation pipeline tests.

Verifies that source → parsed → extracted → translated → reconstructed
maintains structural fidelity.
"""

import pytest
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService


def test_full_pipeline_preserves_structure():
    """End-to-end test: structure preserved through full pipeline."""

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
    config = config_service.get_site_profile('kb.aspose.net')
    engine = TranslationEngine(config)

    from src.translation_engine.parser.hugo_parser import HugoParser
    parser = HugoParser()
    parsed = parser.parse_string(source)

    translated = engine.translate_document(
        parsed=parsed,
        source_lang='en',
        target_lang='de'
    )

    # Count structural elements in source
    source_ordered_lists = source.count('\n1. ') + source.count('\n2. ') + source.count('\n3. ')
    source_bullet_lists = source.count('\n- ')
    source_links = source.count('](')
    source_bold = source.count('**') // 2

    # Count structural elements in translation
    trans_ordered_lists = translated.count('\n1. ') + translated.count('\n2. ') + translated.count('\n3. ')
    trans_bullet_lists = translated.count('\n- ')
    trans_links = translated.count('](')
    trans_bold = translated.count('**') // 2

    # Verify preservation
    assert trans_ordered_lists == source_ordered_lists, \
        f"Ordered lists: {source_ordered_lists} → {trans_ordered_lists}"
    assert trans_bullet_lists == source_bullet_lists, \
        f"Bullet lists: {source_bullet_lists} → {trans_bullet_lists}"
    assert trans_links == source_links, \
        f"Links: {source_links} → {trans_links}"
    assert trans_bold == source_bold, \
        f"Bold: {source_bold} → {trans_bold}"
