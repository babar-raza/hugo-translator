#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test delimiter preservation during ACTUAL TRANSLATION (not just tokenization).

This is the real test - tokenization preserves both, but translation might not.
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

import torch
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

print("Loading M2M100 model (this will take a moment)...")
registry_path = Path("config/model_registry.yaml")
model_registry = ModelRegistry(registry_path)
device = "cpu"
model_loader = ModelLoader(registry=model_registry, device=device)
mt_model = model_loader.load_model("m2m100_1.2b")

print("\n" + "=" * 70)
print("TEST 1: PUA Delimiters During Translation (Current)")
print("=" * 70)

pua_batch = "\uE000\uE000\uE000"
pua_protected = "\uE001\uE001\uE001"
pua_texts = [
    f"Hello{pua_batch}World",
    f"Test{pua_protected}Segment",
    f"A{pua_batch}B{pua_batch}C"
]

print("Translating EN->DE...")
pua_translations = mt_model.translate(pua_texts, src_lang="en", tgt_lang="de")

for i, (orig, trans) in enumerate(zip(pua_texts, pua_translations)):
    print(f"\n[{i+1}] Original:    {orig!r}")
    print(f"    Translation: {trans!r}")
    print(f"    Batch preserved:     {pua_batch in trans} [{'PASS' if pua_batch in trans else 'FAIL'}]")
    print(f"    Protected preserved: {pua_protected in trans} [{'PASS' if pua_protected in trans else 'FAIL'}]")

print("\n" + "=" * 70)
print("TEST 2: Box-Drawing Delimiters During Translation (Proposed)")
print("=" * 70)

box_batch = "═══"
box_protected = "▬▬▬"
box_texts = [
    f"Hello{box_batch}World",
    f"Test{box_protected}Segment",
    f"A{box_batch}B{box_batch}C"
]

print("Translating EN->DE...")
box_translations = mt_model.translate(box_texts, src_lang="en", tgt_lang="de")

for i, (orig, trans) in enumerate(zip(box_texts, box_translations)):
    print(f"\n[{i+1}] Original:    {orig!r}")
    print(f"    Translation: {trans!r}")
    print(f"    Batch preserved:     {box_batch in trans} [{'PASS' if box_batch in trans else 'FAIL'}]")
    print(f"    Protected preserved: {box_protected in trans} [{'PASS' if box_protected in trans else 'FAIL'}]")

print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)

# Count preservation
pua_preserved = sum(1 for trans in pua_translations if pua_batch in trans or pua_protected in trans)
box_preserved = sum(1 for trans in box_translations if box_batch in trans or box_protected in trans)

print(f"\nPUA delimiters preserved:         {pua_preserved}/{len(pua_texts)} ({pua_preserved/len(pua_texts)*100:.0f}%)")
print(f"Box-drawing delimiters preserved: {box_preserved}/{len(box_texts)} ({box_preserved/len(box_texts)*100:.0f}%)")

if box_preserved > pua_preserved:
    print("\n[SUCCESS] Box-drawing delimiters are MORE reliable than PUA")
    print("Recommendation: Proceed with FIX-BT-01 to replace PUA with box-drawing chars")
elif pua_preserved == box_preserved == 0:
    print("\n[CRITICAL] BOTH delimiter types fail during translation")
    print("Need alternative approach: consider semantic markers or different model")
else:
    print("\n[INFO] PUA and box-drawing have similar preservation rates")
    print("May need different delimiter strategy")

print("=" * 70)
