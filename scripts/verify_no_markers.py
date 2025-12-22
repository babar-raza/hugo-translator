#!/usr/bin/env python
"""
Verify no markers in output - create sample output and check for markers.
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


# Read source file
source_path = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en/presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md")

with open(source_path, 'r', encoding='utf-8') as f:
    source_content = f.read()

# Parse
parser = HugoParser()
doc = parser.parse_string(source_content)

# Extract
extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
plan = extractor.extract_from_ast(doc.ast)
units = plan.units

# Simulate translation that adds markers
for unit in units:
    if not unit.do_not_translate:
        unit.translated_text = f"__de__{unit.source_text}__de__"

# Apply and render
renderer = ASTRenderer()
renderer.apply_translations(doc.ast, units)
output_md = renderer.render_to_markdown(doc.ast)

# Save output
output_path = Path("c:/Users/prora/OneDrive/Documents/GitHub/hugo-translator/test_output_bt02.md")
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(output_md)

print(f"Output saved to: {output_path}")

# Check for any markers
marker_count = len(re.findall(r'__[a-z]{2}__', output_md))
print(f"Marker count in output: {marker_count}")

if marker_count == 0:
    print("SUCCESS: No markers found in output!")
else:
    print(f"FAIL: Found {marker_count} markers in output")
    sys.exit(1)
