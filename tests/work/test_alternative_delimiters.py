#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test alternative delimiter strategies that M2M100 might preserve better.

Hypothesis: Natural language markers or recognizable patterns might survive translation better
than special Unicode characters.
"""

import sys
import io
from pathlib import Path

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add user site-packages
import site
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

sys.path.insert(0, str(Path(__file__).parent))

from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

print("Loading M2M100 model...")
registry_path = Path("config/model_registry.yaml")
model_registry = ModelRegistry(registry_path)
model_loader = ModelLoader(registry=model_registry, device="cpu")
mt_model = model_loader.load_model("m2m100_1.2b")

# Test different delimiter strategies
delimiter_strategies = [
    ("HTML Comment", "<!--SEP-->"),
    ("Brackets with ID", "[SEP-12345678]"),
    ("Triple Pipe", "|||"),
    ("Triple Tilde", "~~~"),
    ("Markdown HR", "---"),
    ("Code Block Fence", "```"),
    ("XML Tag", "<SEP/>"),
    ("Double Newline", "\n\n"),
    ("Tab Sequence", "\t\t\t"),
    ("Special Token", "</s>"),  # M2M100 end token
]

print("\n" + "=" * 70)
print("Testing Alternative Delimiter Strategies")
print("=" * 70)

results = []

for name, delimiter in delimiter_strategies:
    # Test with simple case
    test_text = f"Hello{delimiter}World{delimiter}Test"

    try:
        translations = mt_model.translate([test_text], src_lang="en", tgt_lang="de")
        translation = translations[0] if translations else ""

        delimiter_count_in = test_text.count(delimiter)
        delimiter_count_out = translation.count(delimiter)
        preserved = delimiter_count_out == delimiter_count_in

        results.append({
            'name': name,
            'delimiter': delimiter,
            'preserved': preserved,
            'in_count': delimiter_count_in,
            'out_count': delimiter_count_out,
            'translation': translation[:100]
        })

        status = "PASS" if preserved else "FAIL"
        print(f"\n[{status}] {name:20s} ({repr(delimiter)})")
        print(f"      Input delimiters:  {delimiter_count_in}")
        print(f"      Output delimiters: {delimiter_count_out}")
        print(f"      Translation:       {translation[:80]}...")

    except Exception as e:
        print(f"\n[ERROR] {name:20s} - {e}")
        results.append({
            'name': name,
            'delimiter': delimiter,
            'preserved': False,
            'error': str(e)
        })

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

successful = [r for r in results if r.get('preserved', False)]
failed = [r for r in results if not r.get('preserved', False)]

print(f"\nSuccessful strategies: {len(successful)}/{len(results)}")
if successful:
    print("\nStrategies that WORK:")
    for r in successful:
        print(f"  - {r['name']:20s} {repr(r['delimiter'])}")
else:
    print("\n[CRITICAL] NO delimiter strategies preserved during translation!")
    print("This suggests M2M100 cannot reliably preserve delimiters in batch mode.")
    print("\nRecommendation: Consider alternative approaches:")
    print("  1. Use a different model (NLLB, mBART, etc.)")
    print("  2. Disable batch translation (always use individual)")
    print("  3. Use post-processing to realign translations")
    print("  4. Use semantic segmentation markers in source language")

print("=" * 70)
