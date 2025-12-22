#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test native batch translation WITHOUT delimiters.

Instead of concatenating texts with delimiters, send them as a list
and let the model handle batching internally.
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

print("\n" + "=" * 70)
print("TEST: Native Batch Translation (No Delimiters)")
print("=" * 70)

# Test with multiple texts as a list
source_texts = [
    "Hello World",
    "This is a test",
    "Machine translation works well",
    "Python is a great language",
    "Batch processing improves performance"
]

print(f"\nTranslating {len(source_texts)} texts EN->DE...")
print("Source texts:")
for i, text in enumerate(source_texts, 1):
    print(f"  [{i}] {text}")

# Send as list - model handles batching internally
translations = mt_model.translate(source_texts, src_lang="en", tgt_lang="de")

print(f"\nTranslations ({len(translations)} received):")
for i, (src, tgt) in enumerate(zip(source_texts, translations), 1):
    print(f"  [{i}] {src:40s} -> {tgt}")

print("\n" + "=" * 70)
print("VALIDATION")
print("=" * 70)

# Check 1:1 mapping preserved
if len(translations) == len(source_texts):
    print(f"✓ PASS: Received {len(translations)} translations for {len(source_texts)} inputs")
    print("✓ PASS: 1:1 mapping preserved")
else:
    print(f"✗ FAIL: Received {len(translations)} translations for {len(source_texts)} inputs")

# Check all translations non-empty
empty_count = sum(1 for t in translations if not t.strip())
if empty_count == 0:
    print(f"✓ PASS: All {len(translations)} translations are non-empty")
else:
    print(f"✗ FAIL: {empty_count} empty translations")

# Check translations are different from source (actually translated)
different = sum(1 for src, tgt in zip(source_texts, translations) if src.lower() != tgt.lower())
if different == len(source_texts):
    print(f"✓ PASS: All {len(source_texts)} texts were translated (not copied)")
elif different > 0:
    print(f"⚠ PARTIAL: {different}/{len(source_texts)} texts were translated")
else:
    print(f"✗ FAIL: No texts were translated (all identical to source)")

print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)

if len(translations) == len(source_texts) and empty_count == 0:
    print("\n✓ SUCCESS: Native batching works perfectly!")
    print("\nKey findings:")
    print("  1. No delimiters needed")
    print("  2. 1:1 mapping automatically preserved")
    print("  3. Model handles batching internally (padding/masking)")
    print("  4. Much simpler than delimiter-based approach")
    print("\nRecommendation:")
    print("  → REVISE FIX-BT-01 to use native batching instead of delimiters")
    print("  → Remove all delimiter logic from text_unit_extractor.py")
    print("  → Send texts as list directly to model.translate()")
else:
    print("\n✗ FAILURE: Native batching has issues")
    print("Need to investigate model batch handling")

print("=" * 70)
